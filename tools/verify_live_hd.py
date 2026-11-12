"""Compare the live Classic/HD session under matched pinned DOS replay inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

from replay_quick_game import EXPECTED, png_bytes, replay
from verify_synchronized_scene import SCALAR_START, TERRAIN_START, classify, exercise


REFERENCE_SAMPLES = {
    3000: "opening-nest",
    3165: "opening-surface",
    20000: "game-over",
}
INTERACTION_SAMPLES = {
    3000: "opening-nest",
    3165: "opening-surface",
    3300: "menu-to-nest",
    3738: "nest-movement",
    3906: "emergence",
}
ROUTES = {
    "reference": REFERENCE_SAMPLES,
    "transitions": {**INTERACTION_SAMPLES, 4176: "descent", 4287: "menu-to-surface"},
    "movement": {**INTERACTION_SAMPLES, 4288: "surface-movement"},
}
OPENING_TOGGLES = (2994, 3006, 3157, 3171)
REFERENCE_TOGGLES = OPENING_TOGGLES + (19995,)
INTERACTION_TOGGLES = (3290, 3310, 3728, 3745, 3895, 3920, 4166, 4190, 4270)


def ppm_image(ppm):
    magic, dimensions, maximum, rgb = ppm.split(b"\n", 3)
    width, height = (int(value) for value in dimensions.split())
    if magic != b"P6" or maximum != b"255" or len(rgb) != width * height * 3:
        raise ValueError("Invalid presentation image")
    return width, height, rgb


def rgb_bytes(frame):
    width, height, pitch, pixel_format, raw = frame
    if pixel_format != 1 or pitch < width * 4:
        raise ValueError("Expected XRGB8888 software video")
    output = bytearray(width * height * 3)
    for y in range(height):
        source = raw[y * pitch:y * pitch + width * 4]
        start, end = y * width * 3, (y + 1) * width * 3
        output[start:end:3] = source[2::4]
        output[start + 1:end:3] = source[1::4]
        output[start + 2:end:3] = source[0::4]
    return bytes(output)


def decoded_state(pair):
    frame, payload = pair

    def field(offset):
        return struct.unpack_from("<H", payload, SCALAR_START + offset - 0x515FC)[0]

    camera = [field(offset) for offset in (0x51688, 0x5168A)]
    terrain = payload[TERRAIN_START:]
    observation = classify(frame, payload)
    visible_classes = None
    visible_raw = None
    if observation["result"] == "accepted":
        surface = observation["edit"] == 1
        stride, supported = (128, (11, 13)) if surface else (64, (10, 12, 15))
        # The verified 352×335 Edit pane intersects 23×21 tiles. The
        # mailbox also includes offscreen cells and unrelated captured bytes.
        indices = (
            row * stride + col
            for row in range(camera[1], min(64, camera[1] + 21))
            for col in range(camera[0], min(64, camera[0] + 23))
        )
        pairs = [(terrain[index], terrain[8192 + index]) for index in indices]
        visible_raw = hashlib.sha256(bytes(value for cells in pairs for value in cells)).hexdigest()
        visible_classes = hashlib.sha256(bytes(
            first if first == second and first in supported else 0 for first, second in pairs
        )).hexdigest()

    state = {
        "views": list(payload[:3]),
        "ant": [field(offset) for offset in (0x515FC, 0x5160A, 0x5160C)],
        "camera": camera,
        "scene_classification": observation["result"],
        "confirmed_edit_terrain_sha256": visible_classes,
    }
    diagnostics = {
        "full_capture_terrain_sha256": hashlib.sha256(terrain).hexdigest(),
        "visible_raw_tile_pairs_sha256": visible_raw,
    }
    return state, diagnostics


class Trial:
    def __init__(self, session, route, switching, output):
        self.session = session
        self.output = output
        self.samples = ROUTES[route]
        self.schedule = (
            (REFERENCE_TOGGLES if route == "reference" else OPENING_TOGGLES + INTERACTION_TOGGLES)
            if switching else ()
        )
        self.toggles = []
        self.observations = {}

    def after_step(self, host):
        if host.index not in self.schedule and host.index not in self.samples:
            return

        frame = host.frame
        pair = host.capture_pair()
        state, diagnostics = decoded_state(pair) if pair is not None else (None, None)
        guest_marker = (host.index, tuple(host.mouse), len(host.actions), id(host.core))

        if host.index in self.schedule:
            old_mode = self.session.mode
            self.session.toggle()
            mode = self.session.mode
            self.toggles.append({"call": host.index, "from": old_mode, "to": mode})
            if {old_mode, mode} != {"Classic", "HD"}:
                raise AssertionError("Toggle did not change Classic/HD preference")

        if host.index in self.samples:
            name = self.samples[host.index]
            kind, ppm = self.session.presentation()
            width, height, display_rgb = ppm_image(ppm)
            source_rgb = rgb_bytes(frame)
            source_width, source_height = frame[:2]
            if kind == "Classic":
                if (width, height, display_rgb) != (source_width, source_height, source_rgb):
                    raise AssertionError("Classic pixels differ from the original framebuffer")
            elif kind == "HD":
                if pair is None or (width, height) != (1280, 960):
                    raise AssertionError("HD did not render a captured 2x frame")
                # Compare each 2x sample to the unscaled DOS pixels. Resolution
                # alone does not prove that a distinct HD scene was painted.
                sampled = b"".join(
                    display_rgb[y * width * 3:(y + 1) * width * 3][channel::6]
                    for y in range(0, height, 2)
                    for channel in range(3)
                )
                classic_channels = b"".join(
                    source_rgb[y * source_width * 3:(y + 1) * source_width * 3][channel::3]
                    for y in range(source_height)
                    for channel in range(3)
                )
                if sampled == classic_channels:
                    raise AssertionError("HD is identical to nearest-neighbor Classic pixels")
                (self.output / f"{name}-hd.png").write_bytes(png_bytes(width, height, display_rgb))
                (self.output / f"{name}-classic.png").write_bytes(
                    png_bytes(source_width, source_height, source_rgb)
                )
            else:
                raise AssertionError(f"Unknown presentation mode: {kind}")

            self.observations[name] = {
                "call": host.index,
                "state": state,
                "capture_diagnostics": diagnostics,
                "original_rgb_sha256": hashlib.sha256(source_rgb).hexdigest(),
                "presentation": kind,
                "requested_mode": self.session.mode,
                "display_rgb_sha256": hashlib.sha256(display_rgb).hexdigest(),
                "dimensions": [width, height],
            }

        if (guest_marker != (host.index, tuple(host.mouse), len(host.actions), id(host.core))
                or host.frame is not frame or host.capture_pair() != pair):
            raise AssertionError("Presentation changed guest calls, input, state or framebuffer")


def run_trial(args):
    # Launch each trial in a fresh process so no DLL-global state can carry over.
    from live_hd import LiveSession

    session = LiveSession(args.archive, args.core, args.title_state, args.out)
    try:
        trial = Trial(session, args.route, args.trial == "switching", args.out)
        host = session.host
        host.after_step = trial.after_step
        if args.route == "reference":
            replay(host, args.out, session.title_state)
        else:
            exercise(host, args.route, args.out, session.title_state)
        report = {
            "calls": host.index,
            "actions": host.actions,
            "checkpoints": host.checkpoints,
            "observations": trial.observations,
            "toggles": trial.toggles,
        }
        (args.out / "trial.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        session.close()


def compare(route, classic, switching):
    sampled = set(ROUTES[route].values())
    left, right = classic["observations"], switching["observations"]
    matched = sorted(
        name for name in left.keys() & right.keys()
        if all(left[name][key] == right[name][key]
               for key in ("call", "state", "original_rgb_sha256"))
    )
    hd_scenes = sorted({
        sample["state"]["views"][0]
        for sample in right.values()
        if sample["presentation"] == "HD" and sample["state"] is not None
    })
    anchor_names = {"nest", "surface", "terminal-probe"} if route == "reference" else {"nest", "surface"}
    expected_layers = {
        "menu-to-nest": (2, 2),
        "nest-movement": (2, 2),
        "emergence": (1, 1),
        "descent": (2, 2),
        "menu-to-surface": (1, 2),
        "surface-movement": (1, 1),
    }

    def observed_layers(name):
        state = right.get(name, {}).get("state")
        return (state["views"][0], state["ant"][2]) if state is not None else None

    def moved(start, end):
        before = right.get(start, {}).get("state")
        after = right.get(end, {}).get("state")
        return before is not None and after is not None and before["ant"][:2] != after["ant"][:2]

    results = {
        "requested_route_observed": all(
            observed_layers(name) == expected_layers[name] for name in sampled & expected_layers.keys()
        ) and (route == "reference" or moved("menu-to-nest", "nest-movement"))
          and (route != "movement" or moved("emergence", "surface-movement")),
        "game_over_falls_back_to_classic": route != "reference" or (
            right.get("game-over", {}).get("requested_mode") == "HD"
            and right.get("game-over", {}).get("presentation") == "Classic"
        ),
        "same_core_calls": classic["calls"] == switching["calls"],
        "same_guest_input": classic["actions"] == switching["actions"],
        "all_samples_match": set(left) == set(right) == sampled == set(matched),
        "all_original_anchors_match": all(
            {row["file"].removesuffix(".png") for row in trial["checkpoints"] if row["matched"]} == anchor_names
            for trial in (classic, switching)
        ),
        "classic_stayed_classic": not classic["toggles"] and all(
            sample["presentation"] == "Classic" for sample in left.values()
        ),
        "both_hd_scenes_rendered": hd_scenes == [1, 2],
        "all_toggles_ran": len(switching["toggles"]) == (
            len(REFERENCE_TOGGLES) if route == "reference" else len(OPENING_TOGGLES) + len(INTERACTION_TOGGLES)
        ),
    }
    return {
        "passed": all(results.values()),
        "checks": results,
        "matched_samples": matched,
        "raw_capture_differences": sorted(
            name for name in left.keys() & right.keys()
            if left[name]["capture_diagnostics"] != right[name]["capture_diagnostics"]
        ),
        "terrain_comparison": (
            "Exact supported tile classes in the visible Edit pane when both buffers agree; "
            "raw capture differences are separate diagnostics."
        ),
        "unmatched_samples": sorted(sampled - set(matched)),
        "core_calls": {"classic": classic["calls"], "switching": switching["calls"]},
        "classic_anchors": classic["checkpoints"],
        "switching_anchors": switching["checkpoints"],
        "switching_observations": right,
        "classic_observations": left,
        "toggle_events": switching["toggles"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("archive", "core", "title-state", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--route", choices=ROUTES, help=argparse.SUPPRESS)
    parser.add_argument("--trial", choices=("classic", "switching"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.trial:
        if not args.route:
            parser.error("--trial requires --route")
        run_trial(args)
        return 0
    if args.route:
        parser.error("--route requires --trial")

    args.out.mkdir()
    reports = {}
    for route in ROUTES:
        trials = {}
        for mode in ("classic", "switching"):
            trial_out = args.out / f"{route}-{mode}"
            subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()),
                 "--archive", str(args.archive), "--core", str(args.core),
                 "--title-state", str(args.title_state), "--out", str(trial_out),
                 "--route", route, "--trial", mode],
                check=True,
            )
            trials[mode] = json.loads((trial_out / "trial.json").read_text(encoding="utf-8"))
        reports[route] = compare(route, trials["classic"], trials["switching"])

    output = args.out / "verification.json"
    output.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({route: report["checks"] for route, report in reports.items()}, indent=2))
    print(f"Evidence: {output.resolve()}")
    return 0 if all(report["passed"] for report in reports.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
