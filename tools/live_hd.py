"""Play the pinned DOS Quick Game with switchable Classic and HD presentation."""

import argparse
from collections import deque
import ctypes as c
import math
from pathlib import Path
import sys
import time

from hd_red_nest_scene import verify_occupied_red
from hd_surface_scene import verify_east_surface, verify_full_surface
from hd_trails import (
    RED_TRAIL,
    SCENT_MODE_OFFSET,
    SUPPORTED_TRAIL_MODES,
    experimental_title_matches,
    render_trails,
    trail_tiles,
)
from replay_quick_game import (
    ARCHIVE_SHA256,
    BATCH,
    TITLE_STATE_SHA256,
    Host,
    prepare_content,
    verify_file,
)
from save_profile import SaveProfile, SaveProfileError
from verify_synchronized_scene import NEST, RANGES, SURFACE, TERRAIN_START, classify
from windows_audio import WaveOut


CORE_SHA256 = "5789d6d4e6c6fc15e3682db32301428a371b739a0ceaa189ecd1ede5df61e133"
KEYBOARD_EVENT = c.CFUNCTYPE(None, c.c_bool, c.c_uint, c.c_uint32, c.c_uint16)
NATIVE_SIZE = (640, 480)
# The native Load Game path places both tile buffers earlier in conventional RAM.
# Capture both layouts in the same video-boundary sample using two union ranges.
LOADED_TERRAIN_BASES = (0x6E400, 0x83DE0)
TERRAIN_BYTES = RANGES[-1][1]
LEGACY_OFFSETS = tuple(base - loaded for (base, _), loaded in zip(RANGES[-2:], LOADED_TERRAIN_BASES))
TERRAIN_UNION_RANGES = tuple(
    (base, TERRAIN_BYTES + offset) for base, offset in zip(LOADED_TERRAIN_BASES, LEGACY_OFFSETS)
)
LIVE_RANGES = RANGES[:-2] + TERRAIN_UNION_RANGES + ((SCENT_MODE_OFFSET, 1),)
LIVE_CAPACITY = sum(length for _, length in LIVE_RANGES)
LOADED_SURFACE_ROWS = 51  # The loaded game's Caste Control can cover the lower minimap.
GUEST_PERIOD = 1 / 59.940475
PAINT_PERIOD = 1 / 15
OVERLAY_RUNS = tuple(bytes((tone, tone, tone, alpha)) * 40
                     for tone in (0, 130, 195, 255) for alpha in (0, 255))
DOS_KEYS = {
    "BackSpace": 8, "Tab": 9, "Return": 13, "Pause": 19, "Escape": 27,
    "Delete": 127, "Up": 273, "Down": 274, "Right": 275, "Left": 276,
    "Insert": 277, "Home": 278, "End": 279, "Prior": 280, "Next": 281,
    "Shift_R": 303, "Shift_L": 304, "Control_R": 305, "Control_L": 306,
    "Alt_R": 307, "Alt_L": 308,
}
DOS_KEYS.update({f"F{i}": 281 + i for i in (*range(1, 11), 12)})


class GameGeometry(c.Structure):
    _fields_ = [("base_width", c.c_uint), ("base_height", c.c_uint),
                ("max_width", c.c_uint), ("max_height", c.c_uint),
                ("aspect_ratio", c.c_float)]


class SystemTiming(c.Structure):
    _fields_ = [("fps", c.c_double), ("sample_rate", c.c_double)]


class SystemAvInfo(c.Structure):
    _fields_ = [("geometry", GameGeometry), ("timing", SystemTiming)]


def _terrain_payload(payload, offsets):
    first = TERRAIN_START + offsets[0]
    second = TERRAIN_START + TERRAIN_UNION_RANGES[0][1] + offsets[1]
    return payload[:TERRAIN_START] + payload[first:first + TERRAIN_BYTES] + payload[second:second + TERRAIN_BYTES]


class LiveHost(Host):
    def __init__(self, *args):
        self.after_step = None
        self.video_present = False
        self.keyboard = None
        self.audio = None
        self._audio_callback = None
        self._audio_rate = None
        super().__init__(*args)
        configure = self.core.retro_set_scene_capture_v1
        configure.argtypes = [c.POINTER(c.c_uint32), c.c_uint32]
        configure.restype = c.c_bool
        self.get_capture = self.core.retro_get_scene_capture_v1
        self.get_capture.argtypes = [
            c.POINTER(c.c_uint8), c.c_uint32, c.POINTER(c.c_uint64),
            c.POINTER(c.c_uint32), c.POINTER(c.c_uint32),
        ]
        self.get_capture.restype = c.c_uint32
        self.capture_buffer = (c.c_uint8 * LIVE_CAPACITY)()
        spans = (c.c_uint32 * (2 * len(LIVE_RANGES)))(*(value for span in LIVE_RANGES for value in span))
        if not configure(spans, len(LIVE_RANGES)):
            self.close()
            raise RuntimeError("The pinned core rejected the scene capture ranges")

    def environment(self, cmd, data):
        if cmd == 12 and data:
            callback = c.cast(data, c.POINTER(c.c_void_p))[0]
            if callback:
                self.keyboard = KEYBOARD_EVENT(callback)
                return True
        return super().environment(cmd, data)

    def video(self, pointer, width, height, pitch):
        self.video_present = bool(pointer and width and height)
        super().video(pointer, width, height, pitch)

    def run(self, frames):
        for _ in range(frames):
            self.video_present = False
            super().run(1)
            if self.after_step:
                self.after_step(self)

    def _capture_payload(self):
        if not self.video_present or self.frame is None or self.frame[:2] != NATIVE_SIZE:
            return None
        sequence, width, height = c.c_uint64(), c.c_uint32(), c.c_uint32()
        length = self.get_capture(
            self.capture_buffer, LIVE_CAPACITY, c.byref(sequence), c.byref(width), c.byref(height)
        )
        if length != LIVE_CAPACITY or not sequence.value or (width.value, height.value) != NATIVE_SIZE:
            return None
        return bytes(self.capture_buffer)

    def capture_pair(self):
        """Return the original layout for callers that inspect raw captures."""
        payload = self._capture_payload()
        if payload is None:
            return None
        return self.frame, _terrain_payload(payload, LEGACY_OFFSETS)

    def verified_scene(self):
        """Return the accepted canonical payload and scene for the current frame."""
        captured = self._capture_payload()
        if captured is None:
            return None
        frame = self.frame
        if captured[-1] == RED_TRAIL and experimental_title_matches(frame):
            return None  # Keep Experimental Red Trail on its isolated raster path.
        legacy_payload = _terrain_payload(captured, LEGACY_OFFSETS)
        legacy_observation = classify(frame, legacy_payload)
        payload, observation = legacy_payload, legacy_observation
        layout = "legacy"
        if observation["result"] == "terrain-unconfirmed":
            payload = _terrain_payload(captured, (0, 0))
            observation = classify(frame, payload, surface_rows=LOADED_SURFACE_ROWS)
            layout = "loaded"
        if observation["result"] == "accepted":
            return frame, payload, {
                **observation, "terrain_layout": layout, "scent_mode": captured[-1],
            }
        east = verify_east_surface(frame, legacy_payload, legacy_observation, captured[-1])
        if east is not None and not overlay_open(frame):
            return frame, legacy_payload, east
        full = verify_full_surface(frame, legacy_payload, legacy_observation, captured[-1])
        if full is not None and not overlay_open(frame):
            from hd_scene_renderer import neutral_overlay_open

            if not neutral_overlay_open(frame):
                return frame, legacy_payload, full
        occupied_red = verify_occupied_red(frame, legacy_payload, legacy_observation, captured[-1])
        if occupied_red is not None and not overlay_open(frame):
            return frame, legacy_payload, occupied_red
        return None

    def verified_trail(self):
        """Return a coherent Surface frame and a supported native trail mode."""
        captured = self._capture_payload()
        if captured is None or captured[-1] not in SUPPORTED_TRAIL_MODES:
            return None
        frame = self.frame
        mode = captured[-1]
        observation = classify(frame, _terrain_payload(captured, LEGACY_OFFSETS))
        surface = (
            observation.get("edit") == observation.get("map") == SURFACE
            and observation.get("views") == [SURFACE] * 3
        )
        if mode == RED_TRAIL:
            from hd_scene_renderer import neutral_overlay_open

            # Experimental starts without a player ant. The native panes and
            # synchronized view bytes establish the Surface independently.
            if (surface and observation["camera"] == [53, 22]
                    and not overlay_open(frame) and not neutral_overlay_open(frame)
                    and trail_tiles(frame, mode)):
                return frame, mode
            return None
        if (
            observation["result"] in ("terrain-unconfirmed", "ant-unconfirmed")
            and surface
        ):
            return frame, mode
        return None

    def verified_castes(self):
        """Return a coherent Black Nest frame eligible for actor-only HD."""
        pair = self.capture_pair()
        if pair is None:
            return None
        frame, payload = pair
        if payload[:3] != bytes((NEST, NEST, NEST)):
            return None
        observation = classify(frame, payload)
        if (
            observation["result"] == "terrain-unconfirmed"
            and observation.get("edit") == observation.get("map") == NEST
        ):
            return frame
        return None

    def read_view(self):
        pair = self.capture_pair()
        return pair[1][2] if pair else None

    def negotiate_av(self):
        # The core initializes mixer timing here. Call before the first run
        # and before restoring the pinned state, never during live playback.
        get_av = self.core.retro_get_system_av_info
        get_av.argtypes = [c.POINTER(SystemAvInfo)]
        get_av.restype = None
        info = SystemAvInfo()
        get_av(c.byref(info))
        self._audio_rate = int(info.timing.sample_rate)

    def start_audio(self, sink_factory):
        if self.audio is not None:
            return
        try:
            if self._audio_rate is None:
                raise RuntimeError("Start the DOS session before enabling playback")
            self.audio = sink_factory(self._audio_rate)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"DOS audio unavailable: {error}", file=sys.stderr)
            return

        @BATCH
        def receive(pointer, frames):
            if self.audio is not None:
                self.audio.submit(pointer, frames)
            return frames

        self._audio_callback = receive
        self.core.retro_set_audio_sample_batch(self._audio_callback)

    def close(self):
        audio, self.audio = self.audio, None
        try:
            super().close()
        finally:
            if audio is not None:
                audio.close()


class LiveSession:
    """Keep presentation state outside the sole running DOS session."""

    def __init__(self, archive, core, title_state, out, *, save_dir=None):
        self.title_state = None if title_state is None else Path(title_state).resolve()
        archive, core, out = (Path(p).resolve() for p in (archive, core, out))
        verify_file(archive, ARCHIVE_SHA256)
        verify_file(core, CORE_SHA256)
        if self.title_state is not None:
            verify_file(self.title_state, TITLE_STATE_SHA256)
        out.mkdir()
        scratch = out / "scratch"
        scratch.mkdir()
        content = out / "run-reference.dosz"
        prepare_content(archive, content)
        self._started = False
        self._closed = False
        self._profile = None if save_dir is None else SaveProfile(
            Path(save_dir), scratch, content.with_suffix(".pure.zip").name
        )
        try:
            self.host = LiveHost(core, content, scratch)
        except BaseException:
            if self._profile is not None:
                self._profile.close()
            raise
        self.mode = "Classic"
        self.pointer = None
        self.last_pointer = None
        self.mouse_events = deque()
        self.key_events = deque()
        self.keys_held = set()
        self.guest_keys = set()

    def start(self):
        self.host.negotiate_av()
        if self.title_state is not None:
            self.host.run(400)
            self.host.load_title_state(self.title_state)
        self._started = True

    @property
    def audio(self):
        return self.host.audio

    def start_audio(self, sink_factory=WaveOut):
        self.host.start_audio(sink_factory)

    def toggle(self):
        self.mode = "HD" if self.mode == "Classic" else "Classic"
        return self.mode

    def queue_pointer(self, point):
        self.pointer = point

    def queue_button(self, button, pressed, point):
        self.pointer = point
        self.mouse_events.append((button, pressed, point))

    def queue_key(self, code, pressed):
        if (code in self.keys_held) == pressed:
            return
        if pressed:
            self.keys_held.add(code)
        else:
            self.keys_held.remove(code)
        self.key_events.append((pressed, code))

    def release_input(self):
        self.pointer = self.last_pointer
        self.mouse_events.clear()
        for button in (2, 3):
            if self.host.mouse[button]:
                self.mouse_events.append((button, False, self.last_pointer))
        self.keys_held.clear()
        self.key_events.clear()
        self.key_events.extend((False, code) for code in sorted(self.guest_keys))

    def step(self):
        if self.host.keyboard and self.key_events:
            pressed, code = self.key_events.popleft()
            self.host.keyboard(pressed, code, 0, 0)
            if pressed:
                self.guest_keys.add(code)
            else:
                self.guest_keys.discard(code)
        target = self.mouse_events[0][2] if self.mouse_events else self.pointer
        if target is not None and self.last_pointer is None:
            # DOSBox Pure applies half the given deltas in the pinned DOS mode.
            # Establish the guest origin before sending a positioned click.
            self.host.mouse[:2] = [-1500, -1500]
            self.last_pointer = (0, 0)
        else:
            if target is not None:
                self.host.mouse[:2] = [2 * (target[i] - self.last_pointer[i]) for i in (0, 1)]
                self.last_pointer = target
            if self.mouse_events:
                button, pressed, _ = self.mouse_events.popleft()
                self.host.mouse[button] = int(pressed)
        self.host.run(1)

    def presentation(self):
        from hd_scene_renderer import render_caste_only, render_classic, render_dropdown_only, render_hd

        frame = self.host.frame
        if frame is None:
            return "Classic", None
        if self.mode == "HD":
            dropdown = render_dropdown_only(frame)
            if dropdown is not None:
                return "HD", dropdown
        if self.mode == "HD" and not overlay_open(frame):
            scene = self.host.verified_scene()
            if scene:
                return "HD", render_hd(*scene)
            trail = self.host.verified_trail()
            if trail:
                image = render_trails(*trail)
                if image is not None:
                    return "HD", image
            castes = self.host.verified_castes()
            if castes is not None:
                image = render_caste_only(castes)
                if image is not None:
                    return "HD", image
        return "Classic", render_classic(frame)

    def close(self, *, commit_save=True):
        if self._closed:
            return
        self._closed = True
        try:
            self.host.close()
            if self._profile is not None and self._started and commit_save:
                self._profile.commit()
        finally:
            if self._profile is not None:
                self._profile.close()


def overlay_open(frame):
    _, _, pitch, _, raw = frame
    # Solid menu/dialog fills crossing the Edit pane should stay fully native.
    for y in range(42, 377):
        offset = y * pitch + 64 * 4
        row = raw[offset:offset + 352 * 4]
        if any(run in row for run in OVERLAY_RUNS):
            return True
    return False


def native_point(x, y, left, top, width, height, native_width, native_height):
    if not (left <= x < left + width and top <= y < top + height):
        return None
    return ((x - left) * native_width // width, (y - top) * native_height // height)


def hd_3x_ppm(ppm):
    """Scale the 2× native HD frame directly to 3× with nearest-neighbor RGB."""
    width, height = NATIVE_SIZE
    source_stride, target_stride = width * 6, width * 9
    source_header = f"P6\n{width * 2} {height * 2}\n255\n".encode("ascii")
    if not ppm.startswith(source_header) or len(ppm) != len(source_header) + source_stride * height * 2:
        raise ValueError("Expected the native 2× HD frame")

    header = f"P6\n{width * 3} {height * 3}\n255\n".encode("ascii")
    target = bytearray(len(header) + target_stride * height * 3)
    target[:len(header)] = header
    row = bytearray(target_stride)
    destination = len(header)
    for y in range(height * 2):
        start = len(source_header) + y * source_stride
        scan = ppm[start:start + source_stride]
        # Repeat the first sample in each pair on both axes, preserving exact RGB.
        for channel in range(3):
            first = scan[channel::6]
            row[channel::9] = first
            row[channel + 3::9] = first
            row[channel + 6::9] = scan[channel + 3::6]
        target[destination:destination + target_stride] = row
        destination += target_stride
        if y % 2 == 0:
            target[destination:destination + target_stride] = row
            destination += target_stride
    return bytes(target)


class GameWindow:
    def __init__(self, root, session):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.session = session
        self.scale = 1
        self.display_width, self.display_height = NATIVE_SIZE
        self.viewport = None
        self.image = None
        self.painted_frame = None
        self.f11_down = False
        self.closed = False
        self.callback_failed = False

        root.title("SimAnt Respawned")
        root.attributes("-fullscreen", True)
        bar = ttk.Frame(root, padding=(10, 6))
        bar.pack(fill="x")
        self.status = tk.StringVar(value="Classic")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        ttk.Button(bar, text="Quit (Alt+F4)", command=self.close).pack(side="right")
        self.toggle_button = ttk.Button(bar, text="Switch to HD (F11)", command=self.toggle)
        self.toggle_button.pack(side="right")
        self.canvas = tk.Canvas(
            root, width=self.display_width, height=self.display_height,
            bg="black", highlightthickness=0, takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.report_callback_exception
        root.bind("<Alt-KeyPress-F4>", self.close_from_key)
        root.bind("<KeyPress>", self.key_down)
        root.bind("<KeyRelease>", self.key_up)
        root.bind("<FocusOut>", self.focus_out)
        self.canvas.bind("<Configure>", self.resize_viewport)
        self.canvas.bind("<Motion>", self.pointer_move)
        for tk_button, guest_button in ((1, 2), (3, 3)):
            self.canvas.bind(
                f"<ButtonPress-{tk_button}>",
                lambda event, button=guest_button: self.pointer_button(event, button, True),
            )
            self.canvas.bind(
                f"<ButtonRelease-{tk_button}>",
                lambda event, button=guest_button: self.pointer_button(event, button, False),
            )
        self.canvas.focus_set()
        now = time.perf_counter()
        self.next_guest = now
        self.next_paint = now

    def resize_viewport(self, event):
        self.display_width, self.display_height = event.width, event.height
        width, height = NATIVE_SIZE
        scale = max(1, min(4, event.width // width, event.height // height))
        if scale != self.scale:
            self.scale = scale
            self.painted_frame = None
            self.next_paint = 0
        self.place_image()

    def place_image(self):
        if self.image is None:
            return
        width, height = self.image.width(), self.image.height()
        left = (self.display_width - width) // 2
        top = (self.display_height - height) // 2
        self.viewport = (left, top, width, height, *self.native_image_size)
        self.canvas.coords(self.image_item, left, top)

    def event_point(self, event):
        if self.viewport is None:
            return None
        return native_point(event.x, event.y, *self.viewport)

    def pointer_move(self, event):
        point = self.event_point(event)
        if point is not None:
            self.session.queue_pointer(point)

    def pointer_button(self, event, button, pressed):
        self.canvas.focus_set()
        point = self.event_point(event)
        if pressed and point is None:
            return
        self.session.queue_button(button, pressed, point or self.session.pointer)

    def key_down(self, event):
        if event.keysym == "F11":
            if not self.f11_down:
                self.f11_down = True
                self.toggle()
            return "break"
        if self.root.focus_get() != self.canvas:
            return None
        code = DOS_KEYS.get(event.keysym)
        if code is None and len(event.keysym) == 1 and 32 <= ord(event.keysym) < 127:
            code = ord(event.keysym.lower())
        if code is not None:
            self.session.queue_key(code, True)
            return "break"
        return None

    def key_up(self, event):
        if event.keysym == "F11":
            self.f11_down = False
            return "break"
        code = DOS_KEYS.get(event.keysym)
        if code is None and len(event.keysym) == 1 and 32 <= ord(event.keysym) < 127:
            code = ord(event.keysym.lower())
        if code is not None:
            self.session.queue_key(code, False)
            return "break"
        return None

    def focus_out(self, event):
        self.root.after_idle(self.release_if_unfocused)

    def release_if_unfocused(self):
        if self.root.focus_displayof() is None:
            self.session.release_input()
            self.f11_down = False

    def toggle(self):
        mode = self.session.toggle()
        other = "Classic" if mode == "HD" else "HD"
        self.toggle_button.configure(text=f"Switch to {other} (F11)")
        self.painted_frame = None
        self.next_paint = 0

    def paint(self):
        frame = self.session.host.frame
        if frame is None or frame is self.painted_frame:
            return
        kind, ppm = self.session.presentation()
        if ppm is None:
            return
        if kind == "HD" and self.scale == 3:
            ppm = hd_3x_ppm(ppm)
        image = self.tk.PhotoImage(data=ppm, format="PPM")
        if kind == "HD" and self.scale == 1:
            image = image.subsample(2)
        elif kind == "HD" and self.scale == 4:
            image = image.zoom(2)
        elif kind == "Classic" and self.scale > 1:
            image = image.zoom(self.scale)
        self.image = image
        self.native_image_size = frame[:2]
        self.place_image()
        self.canvas.itemconfigure(self.image_item, image=image)
        self.status.set("HD (Classic frame)" if self.session.mode == "HD" and kind == "Classic" else kind)
        self.painted_frame = frame

    def tick(self):
        if self.closed:
            return
        now = time.perf_counter()
        for _ in range(4):
            if now < self.next_guest:
                break
            self.session.step()
            self.next_guest += GUEST_PERIOD
        if now >= self.next_paint:
            self.paint()
            self.next_paint = now + PAINT_PERIOD
        delay = math.ceil((self.next_guest - time.perf_counter()) * 1000)
        self.root.after(max(1, delay), self.tick)

    def close_from_key(self, event):
        self.close()
        return "break"

    def report_callback_exception(self, error_type, error, traceback):
        from tkinter import messagebox

        self.callback_failed = True
        print(f"{error_type.__name__}: {error}", file=sys.stderr)
        try:
            messagebox.showerror("SimAnt Respawned", str(error), parent=self.root)
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("archive", "core", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--title-state", type=Path, help="Pinned title snapshot for replay work")
    parser.add_argument("--save-dir", type=Path, help="Persistent directory for the original DOS saves")
    args = parser.parse_args()
    if sys.platform != "win32" or c.sizeof(c.c_void_p) != 8:
        parser.error("This prototype requires 64-bit Windows Python")

    import tkinter as tk

    try:
        session = LiveSession(args.archive, args.core, args.title_state, args.out, save_dir=args.save_dir)
        succeeded = False
        try:
            session.start()
            session.start_audio()
            root = tk.Tk()
            window = GameWindow(root, session)
            window.tick()
            root.mainloop()
            succeeded = not window.callback_failed
        finally:
            session.close(commit_save=succeeded)
    except SaveProfileError as error:
        details = "\n".join((str(error), *getattr(error, "__notes__", ())))
        parser.exit(1, f"SimAnt Respawned: {details}\n")
    return int(not succeeded)


if __name__ == "__main__":
    sys.exit(main())
