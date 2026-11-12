"""Replay a native Quick Game victory in Classic and with HD switching."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from live_hd import LiveSession
from probe_scene_state import replay_opening, select_view
from replay_quick_game import png_bytes
from verify_live_hd import ppm_image, rgb_bytes
from verify_loaded_quick_game import Controls, guest_marker
from verify_synchronized_scene import RED_NEST, SURFACE, classify, click_at, point


EMERGED = "a82d52eea5232040ce8872d8e507bcd3db1ffef788e4a0988fa7adc79cdbfa24"
VICTORY = "2ed64877483ec5673ab868439439ae5efe63cc392e20f3dbf147b4406e063b77"
EXPECTED = {
    "emerged": (3906, EMERGED),
    "emerged-presentation": (3906, EMERGED),
    "east-cursor-off": (4981, "431cd28566c57b4a8fee3b1d4ab81b5b6cda2e681602aadd4f17675aa4e1adb6"),
    "red-entry": (5722, "e45146b60094f0df5469a00cda6999c198b117f2b3a8577dbc9038f301d3f7a2"),
    "queen-approach": (5856, "de5d65283fa1df12ea2e90e16ba8e5b7ae0bbd9976dc2f830ee7c77055572178"),
    "queen-fight": (6100, "6f9ea83e24e0bcfdbe6638659ccc136c87ce6dbde8c1a45a7471315afde743d3"),
    "queen-defeated": (6550, "9bb7439be21c3a378ba959c98d4b1cce14ca17abb776f0aa9b166dc4a16a6084"),
    "victory": (6656, VICTORY),
    "victory-classic": (6656, VICTORY),
}
EAST_ROUTE = ((286, 204, 247, 209, 260), (362, 204, 247, 209, 260), (450, 208, 247, 225, 320))
RED_ENTRANCE = (510, 212, 279, 225, 650)


class VictoryTrial(Controls):
    def __init__(self, session, output, switching):
        super().__init__(session)
        self.output = output
        self.switching = switching
        self.queued_steps = []
        self.observations = {}
        self.toggles = []

    def run(self, count):
        session = self.session
        for _ in range(count):
            self.queued_steps.append({
                "call": session.host.index + 1,
                "pointer": session.pointer,
                "mouse_events": list(session.mouse_events),
                "key_events": list(session.key_events),
            })
            session.step()

    def toggle(self):
        if self.switching:
            marker = guest_marker(self.session)
            before = self.session.mode
            after = self.session.toggle()
            if guest_marker(self.session) != marker:
                raise AssertionError("Presentation toggle changed the guest state")
            self.toggles.append([self.session.host.index, before, after])

    def park_pointer(self):
        self.session.queue_pointer((430, 409))
        self.run(7)

    def move_on_surface(self, map_x, map_y, edit_x, edit_y, wait, *, double_click=False):
        self.click(485, 72, 16)
        self.click(map_x, map_y, 16)
        self.click(245, 31, 20)
        if double_click:
            self.click(edit_x, edit_y, 2)
        self.click(edit_x, edit_y, wait)

    def sample(self, name):
        session, host = self.session, self.session.host
        frame = host.frame
        native = rgb_bytes(frame)
        width, height = frame[:2]
        pair = host.capture_pair()
        marker = guest_marker(session)
        kind, ppm = session.presentation()
        displayed = ppm_image(ppm)
        if guest_marker(session) != marker:
            raise AssertionError(f"Rendering changed the guest state at {name}")
        if kind == "Classic" and displayed != (width, height, native):
            raise AssertionError(f"Classic pixels differ from the native frame at {name}")
        distinct_hd_pixels = False
        if kind == "HD":
            if displayed[:2] != (width * 2, height * 2):
                raise AssertionError(f"Unexpected HD dimensions at {name}")
            hd_row_bytes = displayed[0] * 3
            source_row_bytes = width * 3
            distinct_hd_pixels = any(
                displayed[2][y * 2 * hd_row_bytes + channel:(y * 2 + 1) * hd_row_bytes:6]
                != native[y * source_row_bytes + channel:(y + 1) * source_row_bytes:3]
                for y in range(height) for channel in range(3)
            )
            (self.output / f"{name}-hd.png").write_bytes(png_bytes(*displayed))
        (self.output / f"{name}.png").write_bytes(png_bytes(width, height, native))
        self.observations[name] = {
            "call": host.index,
            "dimensions": [width, height],
            "native_rgb_sha256": sha256(native).hexdigest(),
            "scene": classify(*pair) if pair else None,
            "requested": session.mode,
            "presentation": kind,
            "presentation_dimensions": list(displayed[:2]),
            "distinct_hd_pixels": distinct_hd_pixels,
            "presentation_sha256": sha256(ppm).hexdigest(),
        }

    def exercise(self):
        host = self.session.host
        replay_opening(host, self.session.title_state, self.output)
        select_view(host, 180, 207, 90)
        click_at(host, 212, 171)
        point(host, 604, 412)
        host.run(110)
        click_at(host, 273, 263, twice=True)
        point(host, 604, 412)
        host.run(280)
        click_at(host, 197, 47, twice=True)
        point(host, 604, 412)
        host.run(140)

        self.sample("emerged")
        self.toggle()
        self.sample("emerged-presentation")
        for move in EAST_ROUTE:
            self.move_on_surface(*move)
        self.park_pointer()
        self.sample("east-cursor-off")
        self.move_on_surface(*RED_ENTRANCE, double_click=True)
        self.park_pointer()
        self.sample("red-entry")
        self.click(245, 192, 2)
        self.click(245, 192, 120)
        self.sample("queen-approach")
        self.click(245, 192, 2)
        self.click(245, 192, 230)
        self.sample("queen-fight")
        self.run(450)
        self.sample("queen-defeated")
        self.click(315, 247, 100)
        self.sample("victory")
        self.toggle()
        self.sample("victory-classic")


def run_trial(args):
    session = LiveSession(args.archive, args.core, args.title_state, args.out)
    trial = VictoryTrial(session, args.out, args.trial == "switching")
    try:
        trial.exercise()
    finally:
        session.close()
        report = {
            "calls": session.host.index,
            "direct_inputs": session.host.actions,
            "queued_steps": trial.queued_steps,
            "opening_anchors": session.host.checkpoints,
            "observations": trial.observations,
            "toggles": trial.toggles,
        }
        (args.out / "trial.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def compare(classic, switching):
    left, right = classic["observations"], switching["observations"]
    mismatched = sorted(name for name, (call, rgb) in EXPECTED.items()
                        if any((row[name]["call"], row[name]["dimensions"], row[name]["native_rgb_sha256"])
                               != (call, [640, 480], rgb) for row in (left, right)))
    scenes_match = all(left[name]["scene"] == right[name]["scene"] for name in left.keys() & right.keys())
    emerged = right["emerged-presentation"]
    victory = right["victory"]
    checks = {
        "opening_anchors_match": classic["opening_anchors"] == switching["opening_anchors"]
        and len(classic["opening_anchors"]) == 2 and all(row["matched"] for row in classic["opening_anchors"]),
        "original_rgb_checkpoints_match": not mismatched and left.keys() == right.keys() == EXPECTED.keys(),
        "guest_calls_match": classic["calls"] == switching["calls"] == 6656,
        "guest_input_matches": classic["direct_inputs"] == switching["direct_inputs"]
        and len(classic["direct_inputs"]) == 38 and classic["queued_steps"] == switching["queued_steps"]
        and len(classic["queued_steps"]) == 2750,
        "synchronized_route_matches": scenes_match and (right["east-cursor-off"]["scene"] or {}).get("ant") == [96, 31, SURFACE]
        and (right["red-entry"]["scene"] or {}).get("ant") == [32, 1, RED_NEST],
        "classic_remains_native": all(row["presentation"] == "Classic" for row in left.values()),
        "live_toggles_match": not classic["toggles"] and switching["toggles"] == [
            [3906, "Classic", "HD"], [6656, "HD", "Classic"],
        ],
        "emerged_frame_renders_hd": emerged["presentation"] == "HD"
        and emerged["presentation_dimensions"] == [1280, 960] and emerged["distinct_hd_pixels"],
        "victory_displays_native_with_hd_requested": victory["requested"] == "HD"
        and victory["presentation"] == "Classic" and victory["presentation_sha256"] == right["victory-classic"]["presentation_sha256"],
    }
    return {"passed": all(checks.values()), "checks": checks, "mismatched_checkpoints": mismatched,
            "classic_observations": left, "switching_observations": right}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("archive", "core", "title-state", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--trial", choices=("classic", "switching"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.trial:
        run_trial(args)
        return 0

    args.out.mkdir()
    reports = []
    for mode in ("classic", "switching"):
        out = args.out / mode
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--archive", str(args.archive),
                        "--core", str(args.core), "--title-state", str(args.title_state), "--out", str(out),
                        "--trial", mode], check=True)
        reports.append(json.loads((out / "trial.json").read_text(encoding="utf-8")))
    report = compare(*reports)
    output = args.out / "verification.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["checks"], indent=2))
    print(f"Evidence: {output.resolve()}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
