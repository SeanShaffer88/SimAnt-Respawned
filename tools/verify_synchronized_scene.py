"""Verify the DOSBox Pure scene mailbox against the pinned SimAnt replay."""

import argparse
from collections import Counter
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import sys

from probe_scene_state import replay_opening, select_view
from replay_quick_game import (
    ARCHIVE_SHA256,
    TITLE_STATE_SHA256,
    Host,
    png_bytes,
    prepare_content,
    replay,
    verify_file,
)


RANGES = ((0x3DF58, 1), (0x514AE, 1), (0x586E2, 1),
          (0x515FC, 0x90), (0x6E6C0, 8192), (0x84630, 8192))
SCALAR_START = 3
TERRAIN_START = SCALAR_START + RANGES[3][1]
CAPACITY = sum(length for _, length in RANGES)
SURFACE, NEST = 1, 2


class CaptureHost(Host):
    def __init__(self, *args, capture_enabled):
        self.phase = None
        self.video_present = False
        self.video_duplicate = False
        self.last_sequence = 0
        self.rows = {}
        self.last_published = None
        self.saved_samples = {}
        self.restores_clear = None
        self.restore_previous_sequence = None
        self.abi_checks = {}
        super().__init__(*args)
        self.mailbox = None
        configure = getattr(self.core, "retro_set_scene_capture_v1", None)
        if capture_enabled and not configure:
            raise RuntimeError("The requested core has no scene mailbox")
        if configure:
            configure.argtypes = [c.POINTER(c.c_uint32), c.c_uint32]
            configure.restype = c.c_bool
            self.mailbox = self.core.retro_get_scene_capture_v1
            self.mailbox.argtypes = [c.POINTER(c.c_uint8), c.c_uint32, c.POINTER(c.c_uint64),
                                     c.POINTER(c.c_uint32), c.POINTER(c.c_uint32)]
            self.mailbox.restype = c.c_uint32
            self.payload = (c.c_uint8 * CAPACITY)()
            self.sequence = c.c_uint64()
            self.width = c.c_uint32()
            self.height = c.c_uint32()
        if capture_enabled:
            spans = (c.c_uint32 * (2 * len(RANGES)))(*(v for span in RANGES for v in span))
            if not configure(spans, len(RANGES)):
                raise RuntimeError("The core rejected the scene mailbox ranges")
            self.abi_checks["invalid_ranges_rejected"] = all(
                not configure((c.c_uint32 * 2)(offset, length), 1)
                for offset, length in ((0, 0), (0, 32769), (0xFFFFFFFF, 1), (0xA0000, 1))
            ) and not configure(spans, 9) and not configure(None, 1)
        elif configure:
            self.abi_checks["disable_request_accepted"] = bool(configure(None, 0))

    def load_title_state(self, source):
        if self.mailbox and self.mailbox_length():
            self.restore_previous_sequence = self.sequence.value
            self.last_sequence = self.restore_previous_sequence
        super().load_title_state(source)
        if self.mailbox:
            self.restores_clear = self.mailbox_length() == 0

    def mailbox_length(self):
        return self.mailbox(self.payload, CAPACITY, c.byref(self.sequence),
                            c.byref(self.width), c.byref(self.height))

    def read_view(self):
        # The opening replay only uses this for its original post-run diagnostic.
        # Its framebuffer hashes remain independent of the scene mailbox.
        return None

    def video(self, pointer, width, height, pitch):
        self.video_present = bool(pointer)
        previous = self.frame
        super().video(pointer, width, height, pitch)
        self.video_duplicate = self.video_present and self.frame == previous

    def run(self, frames):
        for _ in range(frames):
            self.video_present = False
            self.video_duplicate = False
            super().run(1)
            if self.phase:
                self.sample_pair()

    def save_sample(self, key):
        if key in self.saved_samples:
            return
        width, height, pitch, _, raw = self.frame
        rgb = bytearray(width * height * 3)
        for y in range(height):
            scan = raw[y * pitch:y * pitch + width * 4]
            start, end = y * width * 3, (y + 1) * width * 3
            rgb[start:end:3], rgb[start + 1:end:3], rgb[start + 2:end:3] = (
                scan[2::4], scan[1::4], scan[0::4]
            )
        self.saved_samples[key] = (self.index, png_bytes(width, height, rgb))

    def sample_pair(self):
        length = self.mailbox_length()
        previous = self.last_published["sequence"] if self.last_published else None
        row = {"call": self.index, "non_null_video": self.video_present,
               "duplicate_video": self.video_duplicate,
               "capture_sequence": None, "published_sequence": previous}
        if length == 0:
            row["result"] = "unavailable"
        else:
            if length != CAPACITY or not self.video_present or not self.frame:
                raise RuntimeError(f"Unexpected mailbox delivery on core call {self.index}")
            dimensions = (self.width.value, self.height.value)
            if dimensions != self.frame[:2] or self.sequence.value <= self.last_sequence:
                raise RuntimeError(f"Frame identity mismatch on core call {self.index}")
            self.last_sequence = self.sequence.value
            if "short_getter_rejected" not in self.abi_checks:
                small = (c.c_uint8 * 1)(0xA5)
                seq, width, height = c.c_uint64(1), c.c_uint32(2), c.c_uint32(3)
                size = self.mailbox(small, len(small), c.byref(seq), c.byref(width), c.byref(height))
                self.abi_checks["short_getter_rejected"] = (size, small[0], seq.value, width.value,
                                                            height.value) == (0, 0xA5, 1, 2, 3)
            row["capture_sequence"] = self.last_sequence
            row["dimensions"] = dimensions
            report = classify(self.frame, bytes(self.payload))
            row.update(report)
            if report["result"] == "accepted":
                row["published_sequence"] = self.last_sequence
                self.last_published = {"sequence": self.last_sequence, "call": self.index}
                self.save_sample("coherent")
            elif report["result"] == "mixed":
                self.save_sample("mixed")
        self.rows.setdefault(self.phase, []).append(row)


def classify(frame, data, *, surface_rows=64):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4:
        return {"result": "unsupported"}

    def pixel(x, y):
        off = y * pitch + 4 * x
        return tuple(raw[off:off + 3][::-1])

    # These are fixture-specific pixel oracles for the existing Edit and Map panes.
    surface_button = all(pixel(x, y) == (243, 8, 134)
                         for x, y in ((20, 92), (20, 97), (22, 92)))
    nest_button = all(pixel(x, y) == (69, 0, 166)
                      for x, y in ((21, 119), (23, 122), (35, 123)))
    dirt = sum(pixel(x, y) == (85, 44, 4)
               for x in range(80, 400, 13) for y in range(129, 362, 13))
    map_pixels = [pixel(x, y) for x, y in ((460, 150), (500, 280), (535, 242), (550, 95), (565, 315))]
    edit = SURFACE if surface_button and not nest_button and dirt <= 260 else None
    if nest_button and not surface_button and dirt >= 315:
        edit = NEST
    map_view = SURFACE if map_pixels.count((146, 113, 56)) >= 4 else None
    if map_pixels.count((0, 0, 0)) >= 4:
        map_view = NEST
    modes = list(data[:3])

    def field(offset):
        return struct.unpack_from("<H", data, SCALAR_START + offset - 0x515FC)[0]

    ant = [field(offset) for offset in (0x515FC, 0x5160A, 0x5160C)]
    camera = [field(offset) for offset in (0x51688, 0x5168A)]
    report = {"edit": edit, "map": map_view, "views": modes, "ant": ant, "camera": camera}
    if edit is None or map_view is None:
        return {**report, "result": "unknown"}
    if edit != map_view or modes != [edit] * 3:
        return {**report, "result": "mixed"}
    if ant[2] not in (SURFACE, NEST) or any(v >= 64 for v in (*ant[:2], *camera)):
        return {**report, "result": "unknown"}

    buf_a = data[TERRAIN_START:TERRAIN_START + 8192]
    buf_b = data[TERRAIN_START + 8192:]
    if not terrain_matches(pixel, edit, camera, buf_a, buf_b, surface_rows=surface_rows):
        return {**report, "result": "terrain-unconfirmed"}

    # Tile position is projected independently and compared to the original sprite.
    # Require a match when it should be visible and far enough from viewport edges.
    x, y = 71 + 16 * (ant[0] - camera[0]), 49 + 16 * (ant[1] - camera[1])
    if ant[2] == edit and 70 <= x <= 407 and 49 <= y <= 367:
        if not any(pixel(xx, yy) == (255, 243, 4)
                   for yy in range(y - 6, y + 7) for xx in range(x - 6, x + 7)):
            return {**report, "result": "ant-unconfirmed"}
        report["visible_ant"] = [x, y]
    elif ant[2] != edit:
        if not other_layer_sprite_absent(raw, pitch):
            return {**report, "result": "ant-unconfirmed"}
        report["other_layer_sprite_absent"] = True
    return {**report, "result": "accepted"}


def other_layer_sprite_absent(raw, pitch):
    """Allow only the cursor's connected yellow component in the original Edit pane."""
    yellow = set()
    for y in range(42, 377):
        line = raw[y * pitch + 64 * 4:y * pitch + 416 * 4]
        start = 0
        while (offset := line.find(b"\x04\xf3\xff", start)) != -1:
            if offset % 4 == 0:
                yellow.add((64 + offset // 4, y))
            start = offset + 1
    if not yellow:
        return True
    if len(yellow) != 30:
        return False
    component = [yellow.pop()]
    for x, y in component:
        for nx in range(x - 1, x + 2):
            for ny in range(y - 1, y + 2):
                if (nx, ny) in yellow:
                    yellow.remove((nx, ny))
                    component.append((nx, ny))
    return (not yellow and max(x for x, _ in component) - min(x for x, _ in component) == 10
            and max(y for _, y in component) - min(y for _, y in component) == 10)


def terrain_matches(pixel, view, camera, first, second, *, surface_rows=64):
    if view == SURFACE:
        colors = {(146, 113, 56): 11, (130, 130, 130): 13}
        classified = 0
        for y in range(surface_rows):
            for x in range(39):
                terrain = colors.get(pixel(422 + 4 * x, 84 + 4 * y))
                if terrain is None:
                    continue
                classified += 1
                index = y * 128 + 25 + x
                if first[index] != terrain or second[index] != terrain:
                    return False
        return classified >= 1800

    camera_x, camera_y = camera
    solid = matching = tunnels = 0
    for y in range(1, min(20, 64 - camera_y)):
        for x in range(1, min(21, 64 - camera_x)):
            index = (camera_y + y) * 64 + camera_x + x
            code = first[index]
            if code != second[index]:
                return False
            if code not in (10, 12, 15):
                continue
            left, top = 62 + x * 16, 42 + y * 16
            dirt = sum(pixel(left + dx, top + dy) == (85, 44, 4)
                       for dy in (2, 6, 10, 14) for dx in (2, 6, 10, 14))
            if code == 10:
                solid += 1
                matching += dirt >= 9
            else:
                tunnels += dirt <= 8
    return solid >= 250 and matching * 20 >= solid * 19 and tunnels > 0


def point(host, x, y):
    host.move(-1500, -1500)
    host.move(x * 2, y * 2)
    host.run(5)


def click_at(host, x, y, twice=False):
    point(host, x, y)
    host.click(3)
    if twice:
        host.run(2)
        host.click(3)


def menu_switch(host, movement_y):
    point(host, 164, 7)
    host.left_button(True)
    host.run(30)
    host.move(0, movement_y)
    host.run(8)
    host.left_button(False)
    host.run(65)


def exercise(host, route, output, title_state):
    replay_opening(host, title_state, output)
    host.phase = "menu_to_nest"
    select_view(host, 180, 207, 90)

    host.phase = "nest_movement"
    click_at(host, 212, 171)
    point(host, 604, 412)
    host.run(110)
    click_at(host, 273, 263, twice=True)
    point(host, 604, 412)
    host.run(280)

    host.phase = "emergence"
    click_at(host, 197, 47, twice=True)
    point(host, 604, 412)
    host.run(140)

    if route == "transitions":
        host.phase = "descent"
        click_at(host, 225, 221)
        point(host, 604, 412)
        host.run(250)
        host.phase = "menu_to_surface"
        menu_switch(host, 180)
    else:
        host.phase = "surface_movement"
        click_at(host, 305, 151)
        point(host, 604, 412)
        host.run(171)
        click_at(host, 192, 267)
        point(host, 604, 412)
        host.run(171)
    host.phase = None


def case_results(rows, route):
    checks = {
        "menu_to_nest": (NEST, NEST),
        "emergence": (SURFACE, SURFACE),
        "nest_movement": (NEST, NEST),
        **({"descent": (NEST, NEST), "menu_to_surface": (SURFACE, NEST)}
           if route == "transitions" else {"surface_movement": (SURFACE, SURFACE)}),
    }
    results = {}
    for name, (view, layer) in checks.items():
        samples = rows.get(name, [])
        accepted = [row for row in samples if row["result"] == "accepted"]
        final = [row for row in accepted if row["edit"] == view and row["ant"][2] == layer]
        counts = Counter(row["result"] for row in samples)
        result = bool(final and accepted[-1] is final[-1])
        if name in ("emergence", "descent"):
            result = result and any(row["ant"][2] != layer for row in samples if "ant" in row)
        if name.startswith("menu_to_"):
            result = result and any(row["edit"] not in (None, view) for row in samples if "edit" in row)
            if view != layer:
                result = result and bool(final and final[-1].get("other_layer_sprite_absent"))
        if name.endswith("_movement"):
            result = result and len({tuple(row["ant"][:2]) for row in final if "visible_ant" in row}) > 1
        results[name] = {"passed": result, "counts": dict(counts), "final": final[-1] if final else None}
    return results


def publication_checks(phases):
    last = None
    rejected_changed = mixed_published = malformed_pair = 0
    for row in (row for rows in phases.values() for row in rows):
        sequence = row["published_sequence"]
        if row["result"] == "accepted":
            edit = row.get("edit")
            if edit not in (SURFACE, NEST) or row.get("map") != edit or row.get("views") != [edit] * 3:
                mixed_published += 1
            if (not row["non_null_video"] or row["capture_sequence"] != sequence
                    or row.get("dimensions") != (640, 480) or sequence == last):
                malformed_pair += 1
        elif sequence != last:
            rejected_changed += 1
        last = sequence
    return {"rejected_changed_publication": rejected_changed, "mixed_published": mixed_published,
            "malformed_pairs": malformed_pair}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("archive", "core", "title-state", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--core-sha256", required=True)
    parser.add_argument("--route", choices=("transitions", "movement", "reference"), default="transitions")
    parser.add_argument("--capture-off", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or c.sizeof(c.c_void_p) != 8:
        parser.error("This verifier requires 64-bit Windows Python")
    if args.capture_off and args.route != "reference":
        parser.error("--capture-off requires --route reference")

    for file, expected in ((args.archive, ARCHIVE_SHA256), (args.core, args.core_sha256.lower()),
                           (args.title_state, TITLE_STATE_SHA256)):
        verify_file(file, expected)
    output = args.out.resolve()
    output.mkdir()
    scratch = output / "scratch"
    scratch.mkdir()
    content = output / "run-reference.dosz"
    prepare_content(args.archive, content)
    host = CaptureHost(args.core.resolve(), content, scratch, capture_enabled=not args.capture_off)
    try:
        cases = {}
        if args.route == "reference":
            replay(host, output, args.title_state)
            if args.capture_off and host.mailbox:
                host.abi_checks["disabled_capture_empty"] = host.mailbox_length() == 0
        else:
            exercise(host, args.route, output, args.title_state)
            cases = case_results(host.rows, args.route)

        photos = {}
        for kind, (call, image) in host.saved_samples.items():
            file = f"{kind}-{call}.png"
            (output / file).write_bytes(image)
            photos[kind] = {"call": call, "file": file, "png_sha256": hashlib.sha256(image).hexdigest()}
        passed = all(check["matched"] for check in host.checkpoints)
        if not args.capture_off:
            passed = passed and host.restores_clear
        passed = passed and all(host.abi_checks.values())
        publication = publication_checks(host.rows)
        if cases:
            rejected_mixed = sum(case["counts"].get("mixed", 0) for case in cases.values())
            passed = (passed and rejected_mixed > 0 and all(case["passed"] for case in cases.values())
                      and not any(publication.values()))
        report = {"passed": passed, "core_sha256": args.core_sha256.lower(), "route": args.route,
                  "capture_enabled": not args.capture_off, "restores_clear": host.restores_clear,
                  "restore_previous_sequence": host.restore_previous_sequence, "abi_checks": host.abi_checks,
                  "classic_checkpoints": host.checkpoints, "cases": cases, "samples": photos,
                  "publication": publication, "trace": host.rows}
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "trace"}, indent=2))
        return 0 if passed else 1
    finally:
        host.close()


if __name__ == "__main__":
    sys.exit(main())
