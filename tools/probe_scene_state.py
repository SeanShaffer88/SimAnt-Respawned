"""Read the active Quick Game edit view from the pinned DOS build's guest RAM."""

import argparse
import ctypes
import json
from pathlib import Path
import sys

from replay_quick_game import (
    ARCHIVE_SHA256,
    CORE_SHA256,
    EXPECTED,
    Host,
    TITLE_STATE_SHA256,
    prepare_content,
    verify_file,
)

SET_MEMORY_MAPS = 36 | 0x10000
SYSTEM_RAM = 1 << 2
CONVENTIONAL_MEMORY_LIMIT = 0xA0000
VIEW_OFFSET = 0x586E2
VIEW_NAMES = {1: "Surface", 2: "Black Nest", 3: "Red Nest"}
TRACE = Path(__file__).resolve().parents[1] / "docs" / "reference" / "quick-game-trace.json"


class MemoryDescriptor(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("ptr", ctypes.c_void_p),
        ("offset", ctypes.c_size_t),
        ("start", ctypes.c_size_t),
        ("select", ctypes.c_size_t),
        ("disconnect", ctypes.c_size_t),
        ("length", ctypes.c_size_t),
        ("addrspace", ctypes.c_void_p),
    ]


class MemoryMap(ctypes.Structure):
    _fields_ = [
        ("descriptors", ctypes.POINTER(MemoryDescriptor)),
        ("count", ctypes.c_uint),
    ]


class SceneHost(Host):
    def __init__(self, *args):
        self.view_address = None
        self.region_length = None
        super().__init__(*args)

    def environment(self, cmd, data):
        if cmd != SET_MEMORY_MAPS:
            return super().environment(cmd, data)

        self.view_address = None
        self.region_length = None
        if not data:
            return False
        mapping = ctypes.cast(data, ctypes.POINTER(MemoryMap)).contents
        if not mapping.descriptors or not 0 < mapping.count <= 16:
            return False

        # Accept only a unique, directly mapped program-relative RAM window.
        # The descriptor array is owned by the callback, so retain scalars.
        eligible = []
        for index in range(mapping.count):
            region = mapping.descriptors[index]
            if (
                region.flags & SYSTEM_RAM
                and region.ptr
                and (region.offset, region.start, region.select, region.disconnect) == (0, 0, 0, 0)
                and VIEW_OFFSET < region.length <= CONVENTIONAL_MEMORY_LIMIT
            ):
                eligible.append((region.ptr + VIEW_OFFSET, region.length))
        if len(eligible) != 1:
            return False
        self.view_address, self.region_length = eligible[0]
        return True

    def read_view(self):
        address = self.view_address
        if address is None:
            raise RuntimeError("Pinned core did not expose the expected conventional RAM window")
        value = ctypes.string_at(address, 1)
        if value != ctypes.string_at(address, 1) or self.view_address != address:
            raise RuntimeError("Guest view field changed during sampling")
        return value[0]


def observe(host, case, expected, samples=1):
    frame = host.index
    observed = [host.read_view()]
    for _ in range(samples - 1):
        host.run(1)
        observed.append(host.read_view())
    return {
        "case": case,
        "first_core_frame": frame,
        "last_core_frame": host.index,
        "expected_view": VIEW_NAMES[expected],
        "observed_views": [VIEW_NAMES.get(value) for value in observed],
        "observed_values": observed,
        "matched": all(value == expected for value in observed),
    }


def replay_opening(host, title_state, output):
    host.run(400)
    host.load_title_state(title_state)
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    actions = iter(trace["actions"])
    action = next(actions)
    observations = []
    for name, expected in (("nest", 2), ("surface", 1)):
        frame = EXPECTED[name][0]
        while action and action["before_frame"] <= frame:
            host.run(action["before_frame"] - host.index - 1)
            if "relative_mouse" in action:
                host.move(*action["relative_mouse"])
            else:
                host.left_button(action["left_mouse_down"])
            action = next(actions, None)
        host.run(frame - host.index)
        observations.append(observe(host, f"Reference {name}", expected))
        host.capture(name, output)
    return observations


def select_view(host, previous_y, next_y, wait_frames):
    # Start at the previous selection. Releasing on the menu bar cancels.
    if previous_y:
        host.move(0, -previous_y)
    host.run(5)
    host.left_button(True)
    host.run(30)
    if next_y:
        host.move(0, next_y)
    host.run(8)
    host.left_button(False)
    host.run(wait_frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("archive", "core", "title-state", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--wait-frames", type=int, default=90, help="Settling frames after each View menu action")
    args = parser.parse_args()
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        parser.error("This probe requires 64-bit Windows Python")
    if not 30 <= args.wait_frames <= 600:
        parser.error("--wait-frames must be between 30 and 600")

    archive = args.archive.resolve(strict=True)
    core = args.core.resolve(strict=True)
    state = args.title_state.resolve(strict=True)
    output = args.out.resolve()
    verify_file(archive, ARCHIVE_SHA256)
    verify_file(core, CORE_SHA256)
    verify_file(state, TITLE_STATE_SHA256)
    output.mkdir()
    scratch = output / "scratch"
    scratch.mkdir()
    content = output / "run-reference.dosz"
    prepare_content(archive, content)
    host = SceneHost(core, content, scratch)
    try:
        observations = replay_opening(host, state, output)
        previous_y = 180
        for case, next_y, expected in (
            ("Cancel View menu on Surface", 0, 1),
            ("Select Black Nest", 207, 2),
            ("Select Red Nest", 234, 3),
            ("Return to Surface", 180, 1),
        ):
            select_view(host, previous_y, next_y, args.wait_frames)
            observations.append(observe(host, case, expected, samples=3))
            previous_y = next_y

        passed = all(row["matched"] for row in observations + host.checkpoints)
        report = {
            "archive_sha256": ARCHIVE_SHA256,
            "core_sha256": CORE_SHA256,
            "title_state_sha256": TITLE_STATE_SHA256,
            "core_version": host.version,
            "view_offset": hex(VIEW_OFFSET),
            "program_region_bytes": host.region_length,
            "wait_frames": args.wait_frames,
            "sampling": "Guest RAM after retro_run; framebuffer and RAM are not atomic.",
            "observations": observations,
            "classic_checkpoints": host.checkpoints,
            "matched": passed,
        }
        (output / "scene-state.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for row in observations:
            views = " / ".join(view or "Unknown" for view in row["observed_views"])
            status = "PASS" if row["matched"] else "FAIL"
            print(f'{status} {row["first_core_frame"]:>5}  {row["case"]:<30}  {views}')
        return 0 if passed else 1
    finally:
        host.close()


if __name__ == "__main__":
    sys.exit(main())
