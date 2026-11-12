"""Corroborate a panned east Surface scene with the native framebuffer."""

from hd_actors import PLAYER_CENTER, PLAYER_WINDOW, player_support
from hd_cursor import matched_cursor_raster
from verify_synchronized_scene import CAPACITY, SURFACE, TERRAIN_START


EAST_SURFACE_LAYOUT = "legacy-secondary-surface"
_PINK = b"\x86\x08\xf3"
_ORANGE = b"\0\x65\xff"
_MINIMAP_COLORS = {b"\x38\x71\x92": 11, b"\x82" * 3: 13}


def east_surface_camera(camera_x, camera_y):
    """Require the 22×21 viewport to fit within the native 128×64 Surface."""
    return 64 <= camera_x <= 106 and 0 <= camera_y <= 43


def _viewport_matches(pixel, camera_x, camera_y):
    # The Edit pane hides the left part of the native minimap.
    left = max(418, 64 + 4 * camera_x)
    right = 64 + 4 * (camera_x + 22) - 1
    top = 82 + 4 * camera_y
    bottom = top + 83
    if right - left + 1 < 16:
        return False
    edges = (
        [pixel(right, y) for y in range(top, bottom + 1)],
        [pixel(x, top) for x in range(left, right + 1)],
        [pixel(x, bottom) for x in range(left, right + 1)],
    )
    return all(edge.count(_PINK) * 2 > len(edge)
               and all(color in (_PINK, _ORANGE) for color in edge) for edge in edges)


def _secondary_terrain_matches(pixel, payload):
    # Use the full native minimap sample window. Only the second legacy
    # buffer is corroborated here, and the renderer must not use its stone masks.
    second = TERRAIN_START + 8192
    classified = 0
    for y in range(64):
        for x in range(39):
            terrain = _MINIMAP_COLORS.get(pixel(422 + 4 * x, 84 + 4 * y))
            if terrain is not None:
                if payload[second + y * 128 + 25 + x] != terrain:
                    return False
                classified += 1
    return classified >= 1800


def _cursor_clear(frame, center):
    raster = matched_cursor_raster(frame)
    if not raster:
        return False
    width, height = PLAYER_WINDOW
    left = 6 * (center[0] - PLAYER_CENTER[0])
    top = 2 * (center[1] - PLAYER_CENTER[1])
    return all(not (top <= y < top + height * 2
                    and x < left + width * 6 and x + len(rgb) > left)
               for y, x, rgb in raster)


def verify_east_surface(frame, legacy_payload, legacy_observation, scent_mode):
    """Return an east Surface observation only when every native witness agrees."""
    if (scent_mode != 255 or legacy_observation.get("edit") != SURFACE
            or legacy_observation.get("map") != SURFACE
            or legacy_observation.get("views") != [SURFACE] * 3
            or len(legacy_payload) != CAPACITY):
        return None
    camera_x, camera_y = legacy_observation["camera"]
    ant_x, ant_y, ant_layer = legacy_observation["ant"]
    if (not east_surface_camera(camera_x, camera_y) or ant_layer != SURFACE
            or not 0 <= ant_x < 128 or not 0 <= ant_y < 64):
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None

    def pixel(x, y):
        offset = y * pitch + x * 4
        return raw[offset:offset + 3]

    if not _viewport_matches(pixel, camera_x, camera_y) or not _secondary_terrain_matches(pixel, legacy_payload):
        return None
    center = [71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)]
    observation = {
        **legacy_observation, "result": "accepted", "visible_ant": center,
        "terrain_layout": EAST_SURFACE_LAYOUT, "scent_mode": scent_mode,
    }
    if not _cursor_clear(frame, center) or not player_support(frame, legacy_payload, observation)[0]:
        return None
    return observation
