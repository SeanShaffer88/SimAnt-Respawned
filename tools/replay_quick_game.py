"""Replay the pinned SimAnt DOS Quick Game in a disposable directory."""

import argparse
import ctypes as c
import hashlib
import json
import pathlib
import struct
import sys
import zipfile
import zlib

ARCHIVE_SHA256 = "dc2cb4cc6d70b367f03d0754661827e03407ce8d66b5f0320d004cf17ae45103"
CORE_SHA256 = "c43967d99ceb40294ccd5c0847185f46e868ac7479de1ca96fad788e5ae1f27c"
TITLE_STATE_SHA256 = "cf279cc96f03d1253fbe03cf6ce3be289f1e8f8974cc8906880dee493e472f49"
EXPECTED = {
    "nest": (3000, "d7bf1756260d55efee501ab802fff39ba1e7b34ac04037dda83cf374f1066754"),
    "surface": (3165, "5369f6fa56fc1726f35e0b81f908db6c2048c5305f4b503dbb2f406041458f27"),
    "terminal-probe": (20000, "b59466ab87b5b5464386f0abd510d82cc4299de3441fb3518bc46d4b9837184d"),
}


def verify_file(path, expected):
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: expected {expected}, got {actual}")


def prepare_content(archive, content):
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(content, "x") as local:
        for member in original.infolist():
            local.writestr(member, original.read(member))
        local.writestr("DOSBOX.BAT", "@ECHO OFF\r\nCD SIMANT\r\nSIMANT.EXE\r\n")

P = c.c_void_p
B = c.c_bool
U = c.c_uint
N = c.c_size_t
I16 = c.c_int16
ENV = c.CFUNCTYPE(B, U, P)
VID = c.CFUNCTYPE(None, P, U, U, N)
AUD = c.CFUNCTYPE(None, I16, I16)
BATCH = c.CFUNCTYPE(N, P, N)
POLL = c.CFUNCTYPE(None)
STATE = c.CFUNCTYPE(I16, U, U, U, U)


class Game(c.Structure):
    _fields_ = [("path", c.c_char_p), ("data", P), ("size", N), ("meta", c.c_char_p)]


class CoreInfo(c.Structure):
    _fields_ = [("name", c.c_char_p), ("version", c.c_char_p),
                ("extensions", c.c_char_p), ("fullpath", B), ("block_extract", B)]


class Variable(c.Structure):
    _fields_ = [("key", c.c_char_p), ("value", c.c_char_p)]


def png_bytes(width, height, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    stride = width * 3
    rows = (b"\0" + rgb[i:i + stride] for i in range(0, len(rgb), stride))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


class Host:
    def __init__(self, core_path, content, scratch):
        self.core = c.CDLL(str(core_path))
        self.frame = None
        self.index = 0
        self.pixel_format = 0
        self.mouse = [0, 0, 0, 0]
        self.options = {}
        self.actions = []
        self.checkpoints = []
        self.path = str(scratch).encode()
        self._callbacks = [
            ENV(self.environment),
            VID(self.video),
            AUD(lambda left, right: None),
            BATCH(lambda pointer, frames: frames),
            POLL(lambda: None),
            STATE(self.input_state),
        ]
        for name, callback in zip(
            ("environment", "video_refresh", "audio_sample", "audio_sample_batch", "input_poll", "input_state"),
            self._callbacks,
        ):
            fn = getattr(self.core, "retro_set_" + name)
            fn.argtypes = [type(callback)]
            fn.restype = None
            fn(callback)
        info = CoreInfo()
        self.core.retro_get_system_info.argtypes = [c.POINTER(CoreInfo)]
        self.core.retro_get_system_info(c.byref(info))
        self.version = info.version.decode()
        if self.core.retro_api_version() != 1 or self.version != "1.0-preview8":
            raise RuntimeError("Unexpected Libretro API or DOSBox Pure version")
        self.core.retro_init()
        self.core.retro_load_game.argtypes = [c.POINTER(Game)]
        self.core.retro_load_game.restype = B
        self.content_path = str(content).encode()
        game = Game(self.content_path, None, 0, None)
        if not self.core.retro_load_game(c.byref(game)):
            raise RuntimeError("retro_load_game failed")
        self.core.retro_unserialize.argtypes = [P, N]
        self.core.retro_unserialize.restype = B

    def load_title_state(self, source):
        state = source.read_bytes()
        buffer = c.create_string_buffer(state)
        if not self.core.retro_unserialize(buffer, len(state)):
            raise RuntimeError("Could not restore the pinned title-screen snapshot")

    def environment(self, cmd, data):
        if cmd in (9, 31):
            c.cast(data, c.POINTER(c.c_char_p))[0] = self.path
            return True
        if cmd in (3, 17, 51):
            c.cast(data, c.POINTER(B))[0] = cmd == 3
            return True
        if cmd == 10:
            self.pixel_format = c.cast(data, c.POINTER(U))[0]
            return True
        if cmd == 15:
            variable = c.cast(data, c.POINTER(Variable))[0]
            value = self.options.get(variable.key)
            if value is not None:
                variable.value = value
                return True
            return False
        if cmd == 16:
            entries = c.cast(data, c.POINTER(Variable))
            i = 0
            while entries[i].key:
                key = entries[i].key
                default = entries[i].value.split(b";", 1)[-1].strip().split(b"|", 1)[0]
                if key == b"dosbox_pure_cycles":
                    default = b"4720"
                if key == b"dosbox_pure_cpu_core":
                    default = b"normal"
                self.options[key] = default
                i += 1
            return True
        if cmd == 52:
            c.cast(data, c.POINTER(U))[0] = 0
            return True
        if cmd == (47 | 0x10000):
            c.cast(data, c.POINTER(c.c_int))[0] = 3
            return True
        if cmd == (50 | 0x10000):
            c.cast(data, c.POINTER(c.c_float))[0] = 60.0
            return True
        return cmd in (8, 11, 18, 32, 34, 37, 58)

    def video(self, pointer, width, height, pitch):
        if pointer and width and height:
            raw = c.string_at(pointer, pitch * height)
            self.frame = (width, height, pitch, self.pixel_format, raw)

    def input_state(self, port, device, index, control):
        if port == 0 and device == 2 and index == 0 and control < 4:
            return self.mouse[control]
        return 0

    def run(self, frames):
        for _ in range(frames):
            self.core.retro_run()
            self.index += 1
            self.mouse[0] = self.mouse[1] = 0

    def move(self, dx, dy):
        self.actions.append({"before_frame": self.index + 1, "relative_mouse": [dx, dy]})
        self.mouse[0] = dx
        self.mouse[1] = dy
        self.run(1)

    def left_button(self, down):
        self.actions.append({"before_frame": self.index + 1, "left_mouse_down": down})
        self.mouse[2] = int(down)

    def click(self, frames=3):
        self.left_button(True)
        self.run(frames)
        self.left_button(False)
        self.run(frames)

    def capture(self, name, output_dir, required=True):
        width, height, pitch, pixel_format, raw = self.frame
        if (width, height, pixel_format) != (640, 480, 1):
            raise RuntimeError(f"Unexpected capture format at frame {self.index}")
        rgb = bytearray()
        for y in range(height):
            row = raw[y * pitch:(y + 1) * pitch]
            for x in range(width):
                blue, green, red, _ = row[4 * x:4 * x + 4]
                rgb.extend((red, green, blue))
        output = output_dir / (name + ".png")
        output.write_bytes(png_bytes(width, height, rgb))
        expected_frame, expected_hash = EXPECTED[name]
        actual = hashlib.sha256(rgb).hexdigest()
        self.checkpoints.append({
            "frame": self.index,
            "file": output.name,
            "width": width,
            "height": height,
            "rgb_sha256": actual,
            "expected_frame": expected_frame,
            "expected_rgb_sha256": expected_hash,
            "matched": (self.index, actual) == (expected_frame, expected_hash),
            "required": required,
        })

    def close(self):
        self.core.retro_unload_game()
        self.core.retro_deinit()


def replay(host, out, title_state):
    host.run(400)
    if title_state:
        host.load_title_state(title_state)
    host.click()
    host.run(10)
    host.move(150, -84)
    host.run(5)
    host.click()
    host.run(60)
    host.move(114, -224)
    host.run(5)
    host.click()
    host.run(2500)
    host.capture("nest", out)

    host.move(-420, -314)
    host.run(5)
    host.left_button(True)
    host.run(30)
    host.move(0, 180)
    host.run(8)
    host.left_button(False)
    host.run(120)
    host.capture("surface", out)

    host.move(314, -188)
    host.run(5)
    host.left_button(True)
    host.run(30)
    host.move(0, 180)
    host.run(8)
    host.left_button(False)
    host.run(20000 - host.index)
    host.capture("terminal-probe", out, required=bool(title_state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, required=True, help="Pinned SimAnt archive")
    parser.add_argument("--core", type=pathlib.Path, required=True, help="Pinned DOSBox Pure x64 DLL")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="New scratch directory outside the repository")
    parser.add_argument("--title-state", type=pathlib.Path, help="Pinned private snapshot for strict terminal comparison")
    args = parser.parse_args()
    if sys.platform != "win32" or c.sizeof(P) != 8:
        parser.error("This replay requires 64-bit Windows Python")
    archive = args.archive.resolve(strict=True)
    core = args.core.resolve(strict=True)
    title_state = args.title_state.resolve(strict=True) if args.title_state else None
    output = args.out.resolve()
    verify_file(archive, ARCHIVE_SHA256)
    verify_file(core, CORE_SHA256)
    if title_state:
        verify_file(title_state, TITLE_STATE_SHA256)
    output.mkdir()
    scratch = output / "scratch"
    scratch.mkdir()
    content = output / "run-reference.dosz"
    prepare_content(archive, content)
    host = Host(core, content, scratch)
    try:
        replay(host, output, title_state)
        report = {
            "case": "DOS Quick Game opening through passive loss",
            "archive_sha256": ARCHIVE_SHA256,
            "core_sha256": CORE_SHA256,
            "core_version": host.version,
            "initial_state": {"frame": 400, "sha256": TITLE_STATE_SHA256} if title_state else None,
            "core_options": {key.decode(): value.decode() for key, value in host.options.items()},
            "input_frame_base": 1,
            "actions": host.actions,
            "checkpoints": host.checkpoints,
        }
        text = json.dumps(report, indent=2) + "\n"
        (output / "trace.json").write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
        return 0 if all(checkpoint["matched"] for checkpoint in host.checkpoints if checkpoint["required"]) else 1
    finally:
        host.close()


if __name__ == "__main__":
    sys.exit(main())
