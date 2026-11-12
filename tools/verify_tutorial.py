"""Replay the original DOS Tutorial first dig in Classic and with HD switching."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from live_hd import LIVE_CAPACITY, TERRAIN_UNION_RANGES, LiveSession
from replay_quick_game import png_bytes
from verify_live_hd import decoded_state, ppm_image, rgb_bytes
from verify_loaded_quick_game import Controls, guest_marker
from verify_synchronized_scene import TERRAIN_START


NATIVE_SIZE = (640, 480)
EXPECTED = {
    "selector": (487, "2636b9845e52a172483461e2176b853b3f3238974ad90aefd67c802c2711b7ca"),
    "selected": (553, "9b5003d878d7d5bc8da360bf20c6ddf2f4edbb67944d3f20fbbe5cf72716051a"),
    "welcome": (673, "fb65e92da828cffe5e8e37d3a1f12e7e72b772674138dd6a2ba2af8209911274"),
    "first-guidance": (859, "65463610041200c6b5de35418b74e8af2aa8b91c103b54309ae6bc8c3170d21b"),
    "next-guidance": (1045, "e36035d81650f549a2b14de2c1c34ef8c731e4b28bcf756d82cd9507d34fc808"),
    "clear-1086": (1086, "13479fea2b424d5763fa312fb69f8c976c0817a4bb050c8a5f5949387884d515"),
    "tutorial-dig": (1280, "82ecf0cd32eb469ff9ab6c0db66d7fbe843a5182d7ccda763309f434c2a4fef5"),
    "cursor-parked": (1285, "b9a8fe159435316ec4935e2cc900c578e34f3729e1d405466cebd71e60343165"),
}
INPUT_SHA256 = "43f97f964662ddc963f4d61303409d3ad9f1b8eb23d5b9a14325c55f19e06da4"
HD_CHECKPOINTS = {
    "clear-1086": (800, "950b1e2d80bca8207eccf945532386c2a0e835bc73e53701de0b070df5f999fc"),
    "cursor-parked": (801, "e5b2c178fe90de2b6c0b2686c25ab84db19d84c0a05a9feeac20d8bb31ef32b8"),
}
FALLBACK_CHECKPOINTS = {"next-guidance", "tutorial-dig"}
TERRAIN_LAYOUT = "tutorial-nest-truncated-buffers"
TITLE_SHA256 = "583be0378c73158a6d818185d3de1601a689a8937c080b979609ee55feb9156c"
GOLD_RAILS = ((14, 22), (14, 474), (625, 22), (625, 474), (624, 440), (63, 473))
DARK, LIGHT, GRAY, GOLD = map(bytes, ((85, 44, 4), (146, 113, 56), (130, 130, 130), (255, 243, 4)))
DIG_CELLS = ((38, 12), (39, 12))
SWITCH_CALLS = (673, 859, 1045, 1280)
INITIAL_STATE = {"views": [2, 2, 2], "camera": [20, 0], "ant": [37, 11, 2]}
FINAL_STATE = {**INITIAL_STATE, "ant": [39, 12, 2]}


def native_pixel(rgb, x, y):
    start = (y * NATIVE_SIZE[0] + x) * 3
    return rgb[start:start + 3]


def tile_origin(x, y):
    return 63 + 16 * (x - 20), 41 + 16 * y


def tile_colors(rgb, x, y):
    left, top = tile_origin(x, y)
    colors = Counter(native_pixel(rgb, u, v) for v in range(top, top + 16) for u in range(left, left + 16))
    return tuple(colors[color] for color in (DARK, LIGHT, GRAY, GOLD))


def tile_codes(payload, x, y):
    # The first captured byte in each union starts 128 or 208 bytes after Tutorial tile zero.
    index = 64 * y + x
    second_union = TERRAIN_START + TERRAIN_UNION_RANGES[0][1]
    return payload[TERRAIN_START + index - 128], payload[second_union + index - 208]


def classified_tiles(rgb, payload, ant):
    """Classify native RGB tiles independently of the HD renderer, checking both copies."""
    rows = []
    for y in range(3, 27):
        for x in range(21, 55):
            if (x, y) in ((54, 26), tuple(ant[:2])):
                continue
            dark, light, gray, gold = tile_colors(rgb, x, y)
            if gold:
                continue
            first, second = tile_codes(payload, x, y)
            if dark >= 190 and light <= 20 and gray <= 20:
                expected = (10,)
            elif light >= 45 and gray >= 45 and dark <= 90:
                expected = (12, 15)
            else:
                continue
            if first != second or first not in expected:
                raise AssertionError(f"Tutorial tile {(x, y)} disagrees with native RGB: {(first, second)}")
            rows.append((x, y, first, dark, light, gray))
    return rows


def terrain_fingerprint(tiles):
    return len(tiles), sha256(json.dumps(tiles).encode("utf-8")).hexdigest()


def changed_terrain_tiles(native, presented, tiles, ant, pointer):
    """Count authentic soil and floor changes away from the ant and cursor."""
    player_x, player_y = tile_origin(*ant[:2])
    exclusions = ((player_x + 8, player_y + 8), pointer)
    stride = NATIVE_SIZE[0] * 6
    changes = {"soil": 0, "floor": 0}
    for x, y, code, *_ in tiles:
        left, top = tile_origin(x, y)
        if any(left < u + 25 and left + 16 > u - 24 and top < v + 25 and top + 16 > v - 24
               for u, v in exclusions):
            continue
        color, material = (DARK, "soil") if code == 10 else (LIGHT, "floor")
        doubled = color * 2
        changed = 0
        for v in range(top, top + 16):
            for u in range(left, left + 16):
                if native_pixel(native, u, v) != color:
                    continue
                start = v * 2 * stride + u * 6
                if presented[start:start + 6] != doubled or presented[start + stride:start + stride + 6] != doubled:
                    changed += 1
        if changed >= 8:
            changes[material] += 1
    return changes


class TutorialTrial(Controls):
    def __init__(self, session, output, switching):
        super().__init__(session)
        self.output = output
        self.switching = switching
        self.steps = []
        self.observations = {}
        self.switch_calls = []

    def run(self, count):
        session = self.session
        for _ in range(count):
            self.steps.append([session.host.index + 1, session.pointer, list(session.mouse_events),
                               list(session.key_events)])
            session.step()

    def switch(self):
        if self.switching:
            host = self.session.host
            marker, raw = guest_marker(self.session), host._capture_payload()
            previous = self.session.mode
            if self.session.toggle() == previous or guest_marker(self.session) != marker or host._capture_payload() != raw:
                raise AssertionError(f"Presentation switch changed guest state at call {host.index}")
            self.switch_calls.append(host.index)

    def sample(self, name):
        session, host = self.session, self.session.host
        frame = host.frame
        payload, pair = host._capture_payload(), host.capture_pair()
        if frame[:2] != NATIVE_SIZE or payload is None or len(payload) != LIVE_CAPACITY or pair is None:
            raise AssertionError(f"Missing synchronized native frame at {name}")
        native = rgb_bytes(frame)
        state, _ = decoded_state(pair)
        native_rgb = sha256(native).hexdigest()
        marker = guest_marker(session)
        previous = session.mode
        if self.switching and name in HD_CHECKPOINTS and previous == "Classic":
            session.toggle()
        requested = session.mode
        presentation, ppm = session.presentation()
        shown = ppm_image(ppm)
        exact_classic = presentation == "Classic" and shown == (*NATIVE_SIZE, native)
        restored_classic = False
        changed_tiles = None
        terrain_layout = None
        tiles = classified_tiles(native, payload, state["ant"]) if name in HD_CHECKPOINTS else None
        if presentation == "HD":
            if shown[:2] != (1280, 960):
                raise AssertionError(f"Unexpected HD dimensions at {name}")
            if tiles is not None:
                changed_tiles = changed_terrain_tiles(native, shown[2], tiles, state["ant"], session.pointer)
            scene = host.verified_scene()
            terrain_layout = scene[2].get("terrain_layout") if scene else None
            session.toggle()
            restored, restored_ppm = session.presentation()
            restored_classic = restored == "Classic" and ppm_image(restored_ppm) == (*NATIVE_SIZE, native)
            session.toggle()
            (self.output / f"{name}-hd.png").write_bytes(png_bytes(*shown))
        if session.mode != previous:
            session.toggle()
        same_guest = guest_marker(session) == marker and host._capture_payload() == payload
        if not same_guest:
            raise AssertionError(f"Presentation changed the same-call native guest state at {name}")

        row = {"call": host.index, "native_rgb_sha256": native_rgb, "state": state, "requested": requested,
               "presentation": presentation, "dimensions": list(shown[:2]), "changed_terrain_tiles": changed_tiles,
               "exact_classic": exact_classic, "same_call_classic_restored": restored_classic,
               "same_call_guest_unchanged": same_guest, "terrain_layout": terrain_layout,
               "raw_capture_sha256": sha256(payload).hexdigest()}
        self.observations[name] = row
        (self.output / f"{name}.png").write_bytes(png_bytes(*NATIVE_SIZE, native))
        (self.output / f"{name}.capture").write_bytes(payload)
        if host.index >= 1045:
            title = bytes(channel for y in range(25, 40) for x in range(225, 411)
                          for channel in native_pixel(native, x, y))
            row["title_sha256"] = sha256(title).hexdigest()
            row["maximized_edit_border"] = all(native_pixel(native, x, y) == GOLD for x, y in GOLD_RAILS)
            row["dig_cells"] = [
                {"cell": [x, y], "codes": list(tile_codes(payload, x, y)), "rgb_counts": list(tile_colors(native, x, y))}
                for x, y in DIG_CELLS
            ]
        if tiles is not None:
            row["classified_terrain"] = list(terrain_fingerprint(tiles))

    def exercise(self):
        self.run(1)
        self.click(245, 325, 12)
        self.click(320, 283, 62)
        self.sample("selector")
        self.click(201, 165, 60)
        self.sample("selected")
        self.run(120)
        self.sample("welcome")
        self.switch()
        self.click(317, 260, 180)
        self.sample("first-guidance")
        self.switch()
        self.click(317, 269, 180)
        self.switch()
        self.sample("next-guidance")
        self.click(317, 260, 35)
        self.sample("clear-1086")
        self.click(382, 248, 2)
        self.click(382, 248, 180)
        self.sample("tutorial-dig")
        self.switch()
        self.session.queue_pointer((604, 412))
        self.run(5)
        self.sample("cursor-parked")


def run_trial(args):
    session = LiveSession(args.archive, args.core, args.title_state, args.out)
    trial = TutorialTrial(session, args.out, args.trial == "switching")
    try:
        session.start()
        trial.exercise()
    finally:
        session.close(commit_save=False)
        report = {"calls": session.host.index, "direct_inputs": session.host.actions, "input": trial.steps,
                  "switch_calls": trial.switch_calls, "observations": trial.observations}
        write_json(args.out / "trial.json", report)


def write_json(path, report):
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def native_dig(observations):
    def witnesses(name):
        return observations[name]["dig_cells"]

    before = witnesses("clear-1086")
    if not all(cell["codes"] == [10, 10] and cell["rgb_counts"][0] >= 190 and cell["rgb_counts"][2] <= 20
               for cell in before):
        return False
    for stage in ("tutorial-dig", "cursor-parked"):
        vacant, occupied = witnesses(stage)
        if vacant["codes"] != [12, 12] or occupied["codes"] != [1, 1]:
            return False
        if any(not (dark <= 90 and light >= 45 and gray >= 45) for dark, light, gray, _ in
               (vacant["rgb_counts"], occupied["rgb_counts"])):
            return False
        if vacant["rgb_counts"][3] != 0 or occupied["rgb_counts"][3] != 11:
            return False
    return True


def compare(classic, switching):
    trials = classic, switching
    left, right = (trial["observations"] for trial in trials)
    anchor_mismatches = {label: [name for name, (call, rgb) in EXPECTED.items()
                                 if (rows[name]["call"], rows[name]["native_rgb_sha256"]) != (call, rgb)]
                         for label, rows in (("classic", left), ("switching", right))}
    frozen_states = {name: INITIAL_STATE for name in ("welcome", "first-guidance", "next-guidance", "clear-1086")}
    frozen_states.update({name: FINAL_STATE for name in ("tutorial-dig", "cursor-parked")})
    frozen_states.update({"selector": {"views": [1, 0, 255], "camera": [0, 0], "ant": [0, 0, 0]},
                          "selected": {**INITIAL_STATE, "camera": [26, 1]}})
    checks = {
        "original_inputs": classic["input"] == switching["input"] and all(
            not trial["direct_inputs"] and len(trial["input"]) == 885 and trial["calls"] == 1285 and
            sha256(json.dumps(trial["input"], separators=(",", ":")).encode("utf-8")).hexdigest() == INPUT_SHA256
            for trial in trials),
        "original_native_rgb": not any(anchor_mismatches.values()),
        "original_native_state": all(all(row["state"][key] == value for key, value in frozen_states[name].items())
                                     for rows in (left, right) for name, row in rows.items()),
        "original_tutorial_pane": all(row["title_sha256"] == TITLE_SHA256 and row["maximized_edit_border"]
                                      for rows in (left, right) for row in rows.values() if row["call"] >= 1045),
        "new_tunnel_floor_and_yellow_ant": all(native_dig(rows) for rows in (left, right)),
        "original_dual_copy_terrain": all(tuple(rows[name]["classified_terrain"]) == expected
                                          for rows in (left, right) for name, expected in HD_CHECKPOINTS.items()),
        "host_switch_calls": classic["switch_calls"] == [] and switching["switch_calls"] == list(SWITCH_CALLS),
        "classic_exact": all(row["requested"] == row["presentation"] == "Classic" and row["exact_classic"]
                             for row in left.values()),
        "hd_clear_and_parked": all(right[name]["requested"] == right[name]["presentation"] == "HD"
                                   and right[name]["same_call_classic_restored"]
                                   and right[name]["terrain_layout"] == TERRAIN_LAYOUT for name in HD_CHECKPOINTS),
        "hd_repaints_confirmed_soil_and_floor": all(
            (counts := right[name]["changed_terrain_tiles"]) is not None
            and counts["soil"] >= 2 and counts["floor"] >= 2 for name in HD_CHECKPOINTS),
        "classic_fallbacks": all(right[name]["requested"] == "HD" and right[name]["exact_classic"]
                                 for name in FALLBACK_CHECKPOINTS),
        "same_call_guest_unchanged": all(row["same_call_guest_unchanged"]
                                         for rows in (left, right) for row in rows.values()),
    }
    return {"passed": all(checks.values()), "checks": checks, "anchor_mismatches": anchor_mismatches,
            "raw_mailbox_sha256_diagnostic": {name: [left[name]["raw_capture_sha256"], right[name]["raw_capture_sha256"]]
                                              for name in EXPECTED}}


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
    reports, exits = {}, {}
    for mode in ("classic", "switching"):
        out = args.out / mode
        with (args.out / f"{mode}.log").open("x", encoding="utf-8") as log:
            exits[mode] = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--archive", str(args.archive), "--core",
                 str(args.core), "--title-state", str(args.title_state), "--out", str(out), "--trial", mode],
                stdout=log, stderr=subprocess.STDOUT,
            ).returncode
        path = out / "trial.json"
        if path.is_file():
            reports[mode] = json.loads(path.read_text(encoding="utf-8"))
    complete = not any(exits.values()) and all(
        reports.get(mode, {}).get("observations", {}).keys() == EXPECTED.keys() for mode in exits
    )
    result = compare(reports["classic"], reports["switching"]) if complete else {"passed": False, "checks": {}}
    result["checks"]["complete_trials"] = complete
    result["child_exit_codes"] = exits
    output = args.out / "verification.json"
    write_json(output, result)
    print(json.dumps(result["checks"], indent=2))
    print(f"Evidence: {output.resolve()}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
