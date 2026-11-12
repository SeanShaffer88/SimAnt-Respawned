"""Paint small roots only inside verified Quick Game Black Nest soil."""

from hd_actors import PLAYER_CENTER, PLAYER_WINDOW
from hd_surface_scene import quick_game_title_matches
from verify_synchronized_scene import NEST


_SOIL_BGR = b"\x04\x2c\x55"
_SOIL_PALETTE = (_SOIL_BGR, b"\x41\x41\x41")
_DELTA = {"a": (8, 4, 1), "b": (5, 3, 1), "s": (-3, -2, -1)}
_ROOT = tuple(
    (x + 6, y + 6, _DELTA[cell])
    for y, row in enumerate((
        "..sa...............",
        "..saa..............",
        "..sa...............",
        "..sa...............",
        "....sa.............",
        "....saa............",
        ".....sa............",
        ".....saa...........",
        "......sabb.........",
        ".......a..bb.......",
        ".......sa...bb.....",
        "........a.....b....",
        "........sa.....b...",
        ".........a.....b...",
        "..........a........",
        "...........a.......",
        "............b......",
        ".............b.....",
        "..............b....",
    ))
    for x, cell in enumerate(row) if cell in _DELTA
)
_ROOT_SITES = frozenset((x // 2, y // 2) for x, y, _ in _ROOT)


def _safe_soil(raw, pitch, left, top, player):
    def pixel(x, y):
        offset = y * pitch + x * 4
        return raw[offset:offset + 3]

    for dx, dy in _ROOT_SITES:
        x, y = left + dx, top + dy
        if player is not None and player[0] <= x < player[2] and player[1] <= y < player[3]:
            return False
        if pixel(x, y) != _SOIL_BGR:
            return False
        neighbors = [pixel(u, v) for v in range(y - 2, y + 3) for u in range(x - 2, x + 3)]
        if neighbors.count(_SOIL_BGR) < 19 or any(color not in _SOIL_PALETTE for color in neighbors):
            return False
    return True


def paint_nest_roots(pixels, frame, first, second, observation):
    """Shade the existing HD soil using a world-selected 2× root stencil."""
    if (observation.get("terrain_layout") not in ("legacy", "loaded")
            or observation.get("edit") != NEST or observation.get("map") != NEST
            or observation.get("views") != [NEST] * 3):
        return
    width, _, pitch, _, raw = frame
    if not quick_game_title_matches(raw, pitch):
        return

    player = None
    if center := observation.get("visible_ant"):
        x, y = (coordinate - offset for coordinate, offset in zip(center, PLAYER_CENTER))
        player = (x, y, x + PLAYER_WINDOW[0], y + PLAYER_WINDOW[1])
    camera_x, camera_y = observation["camera"]
    output_stride = width * 6
    for gy in range(1, min(20, 64 - camera_y)):
        wy, top = camera_y + gy, 42 + 16 * gy
        for gx in range(1, min(21, 64 - camera_x)):
            wx, left = camera_x + gx, 62 + 16 * gx
            if ((wx * 0x45D9F3B) ^ (wy * 0x27D4EB2D)) % 37:
                continue
            index = wy * 64 + wx
            if first[index] != 10 or second[index] != 10:
                continue
            soil = sum(raw[y * pitch + x * 4:y * pitch + x * 4 + 3] == _SOIL_BGR
                       for y in range(top, top + 16) for x in range(left, left + 16))
            if soil < 190 or not _safe_soil(raw, pitch, left, top, player):
                continue
            for dx, dy, deltas in _ROOT:
                start = (2 * top + dy) * output_stride + (2 * left + dx) * 3
                for channel, delta in enumerate(deltas):
                    pixels[start + channel] += delta
