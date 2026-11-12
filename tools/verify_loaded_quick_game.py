"""Save and reopen a native Quick Game, then verify both live HD views."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from hd_cursor import matched_cursor_raster
from hd_scene_renderer import BOTTOM, LEFT, RIGHT, TOP
from hd_ui import MENU_BAR, matching_ui
from hd_workspace import WORKSPACE_RGB, verified_workspace_runs
from live_hd import LiveSession
from verify_live_hd import ppm_image, rgb_bytes
from verify_synchronized_scene import NEST, SURFACE, classify


class Controls:
    def __init__(self, session):
        self.session = session

    def run(self, count):
        for _ in range(count):
            self.session.step()

    def click(self, x, y, wait=20):
        point = (x, y)
        self.session.queue_pointer(point)
        self.run(3)
        self.session.queue_button(2, True, point)
        self.run(3)
        self.session.queue_button(2, False, point)
        self.run(wait)

    def menu(self, x, y):
        self.session.queue_pointer((x, 14))
        self.run(5)
        self.session.queue_button(2, True, (x, 14))
        self.run(30)
        self.session.queue_pointer((x, y))
        self.run(8)
        self.session.queue_button(2, False, (x, y))
        self.run(40)

    def enter_name(self):
        for code in b"parity":
            self.session.queue_key(code, True)
            self.run(3)
            self.session.queue_key(code, False)
            self.run(3)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_save(profile):
    overlay = profile / "run-reference.pure.zip"
    with ZipFile(overlay) as archive:
        save = archive.read("SIMANT/PARITY.ANT")
    return {"bytes": len(save), "sha256": sha256(save), "profile_sha256": sha256(overlay.read_bytes())}


def scene(session):
    pair = session.host.capture_pair()
    if pair is None:
        raise AssertionError(f"No synchronized scene at call {session.host.index}")
    return classify(*pair)


def guest_marker(session):
    host = session.host
    return (
        host.index, host.frame, host.capture_pair(), host.verified_scene(), tuple(host.mouse), tuple(host.actions),
        session.pointer, session.last_pointer, tuple(session.mouse_events), tuple(session.key_events),
        frozenset(session.keys_held), frozenset(session.guest_keys),
    )


def verify_raster(source, hd, width, height, *, cursor_frame=None, workspace_frame=None):
    """Require terrain, controls, and exact cursor and desktop changes where verified."""
    terrain_changed = False
    ui_changed = set()
    ui_regions = tuple(bounds for bounds, _ in matching_ui(
        tuple(source[channel::3] for channel in range(3)), width
    ))
    terrain = (LEFT, TOP, RIGHT, BOTTOM)
    allowed = sorted((*ui_regions, terrain))
    cursor_raster = matched_cursor_raster(cursor_frame) if cursor_frame is not None else ()
    cursor_rows = {row: (left, rgb) for row, left, rgb in cursor_raster}
    workspace_rows = {}
    if workspace_frame is not None:
        for y, left, right in verified_workspace_runs(workspace_frame):
            workspace_rows.setdefault(y, []).append((left * 6, right * 6))
    row_bytes = width * 6
    for y in range(height):
        regions = [bounds for bounds in allowed if bounds[1] <= y < bounds[3]]
        row = source[y * width * 3:(y + 1) * width * 3]
        expanded = bytearray(row_bytes)
        for channel in range(3):
            expanded[channel::6] = expanded[channel + 3::6] = row[channel::3]
        for subrow in range(2):
            display_y = y * 2 + subrow
            begin = display_y * row_bytes
            display = bytearray(hd[begin:begin + row_bytes])
            if display_y in cursor_rows:
                left, cursor = cursor_rows[display_y]
                right = left + len(cursor)
                if display[left:right] != cursor:
                    raise AssertionError("HD cursor did not match its verified raster")
                # Cursor paint must not count toward a required terrain/control repaint.
                display[left:right] = expanded[left:right]
            for left, right in workspace_rows.get(y, ()):
                if display[left:right] != WORKSPACE_RGB * ((right-left)//3):
                    raise AssertionError("HD desktop did not match its verified raster")
                # Desktop paint also must not count toward terrain/control assertions.
                display[left:right] = expanded[left:right]
            end = 0
            for bounds in regions:
                left, right = bounds[0] * 6, bounds[2] * 6
                if display[end:left] != expanded[end:left]:
                    raise AssertionError("HD changed pixels outside the verified regions")
                if display[left:right] != expanded[left:right]:
                    if bounds == terrain:
                        terrain_changed = True
                    else:
                        ui_changed.add(bounds)
                end = right
            if display[end:] != expanded[end:]:
                raise AssertionError("HD changed pixels outside the verified regions")
    if not terrain_changed:
        raise AssertionError("HD did not repaint terrain")
    if MENU_BAR not in ui_changed or len(ui_changed) < 2:
        raise AssertionError("HD did not repaint the menu bar and a verified control")
    return sorted(ui_changed)


def verify_view(session, view):
    host = session.host
    if session.mode == "Classic":
        session.toggle()
    # The native Edit and Map panes can finish on different draws.
    for _ in range(120):
        verified = host.verified_scene()
        if verified and verified[2]["views"] == [view] * 3:
            kind, hd_image = session.presentation()
            if kind == "HD":
                break
        session.step()
    else:
        pair = host.capture_pair()
        raise AssertionError(f"Loaded view {view} did not render in HD: {classify(*pair) if pair else None}")

    marker = guest_marker(session)
    frame, payload, observation = verified
    source = rgb_bytes(frame)
    width, height = frame[:2]
    hd_width, hd_height, hd_rgb = ppm_image(hd_image)
    if (hd_width, hd_height) != (width * 2, height * 2):
        raise AssertionError("Expected a 2× HD frame")
    ui_regions = verify_raster(source, hd_rgb, width, height, cursor_frame=frame, workspace_frame=frame)

    if session.toggle() != "Classic":
        raise AssertionError("Toggle did not select Classic")
    kind, classic = session.presentation()
    if kind != "Classic" or ppm_image(classic) != (width, height, source):
        raise AssertionError("Classic did not reproduce the current DOS framebuffer")
    if guest_marker(session) != marker:
        raise AssertionError("Switching to Classic changed the live guest")

    if session.toggle() != "HD" or session.presentation() != ("HD", hd_image):
        raise AssertionError("Switching back did not restore the same HD frame")
    if guest_marker(session) != marker:
        raise AssertionError("Switching back to HD changed the live guest")
    return {
        "call": host.index,
        "scene": observation,
        "original_rgb_sha256": sha256(source),
        "capture_sha256": sha256(payload),
        "hd_rgb_sha256": sha256(hd_rgb),
        "styled_ui_regions": ui_regions,
        "same_live_guest_after_toggles": True,
    }


def run_trial(args):
    base = args.out
    profile = base / "save-profile"
    trial = base / args.trial
    session = LiveSession(args.archive, args.core, args.title_state, trial, save_dir=profile)
    controls = Controls(session)
    success = False
    try:
        session.start()
        controls.run(1)
        controls.click(245, 325, 12)
        controls.click(320, 283, 62)
        if args.trial == "save":
            controls.click(377, 171, 2200)
            saved_scene = scene(session)
            if saved_scene["views"] != [NEST] * 3:
                raise AssertionError(f"Quick Game did not reach Black Nest: {saved_scene}")
            controls.menu(22, 98)  # File > Save As
            controls.enter_name()
            controls.click(208, 343)
            report = {"saved_scene": saved_scene}
        else:
            saved = json.loads((base / "save" / "trial.json").read_text(encoding="utf-8"))
            controls.click(375, 309)  # Load Game
            controls.click(204, 128, 5)
            controls.click(208, 307, 50)
            loaded_scene = scene(session)
            for field in ("views", "ant", "camera"):
                if loaded_scene[field] != saved["saved_scene"][field]:
                    raise AssertionError(f"Native load changed saved {field}: {loaded_scene}")
            # Bring Edit to the foreground, then resume through its Pause control.
            controls.click(245, 31, 20)
            controls.click(40, 175, 30)
            controls.click(40, 175, 60)
            nest = verify_view(session, NEST)
            controls.menu(167, 104)  # View > Surface
            surface = verify_view(session, SURFACE)
            controls.menu(167, 118)  # View > Black Nest
            nest_return = verify_view(session, NEST)
            controls.click(212, 171, 110)
            moved = scene(session)
            if moved["ant"][:2] == nest_return["scene"]["ant"][:2]:
                raise AssertionError(f"Yellow Ant did not move after the switches: {moved}")
            report = {
                "loaded_scene": loaded_scene,
                "black_nest": nest,
                "surface": surface,
                "black_nest_return": nest_return,
                "ant_after_movement": moved["ant"],
            }
        success = True
    finally:
        session.close(commit_save=success)
    report["save"] = read_save(profile)
    if args.trial == "reopen" and report["save"] != saved["save"]:
        raise AssertionError("Reopening and playing without saving changed the native save profile")
    (trial / "trial.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "core", "title-state", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--trial", choices=("save", "reopen"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.trial:
        return run_trial(args)

    args.out.mkdir()
    reports = {}
    for trial in ("save", "reopen"):
        subprocess.run([
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--archive", str(args.archive), "--core", str(args.core),
            "--title-state", str(args.title_state), "--out", str(args.out), "--trial", trial,
        ], check=True)
        reports[trial] = json.loads((args.out / trial / "trial.json").read_text(encoding="utf-8"))
    output = args.out / "verification.json"
    output.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(f"Loaded Quick Game rendered HD Surface and Black Nest. Evidence: {output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
