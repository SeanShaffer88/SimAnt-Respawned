"""Corroborate additional Surface scenes with the native framebuffer."""

from hashlib import sha256

from hd_actors import PLAYER_HEADING, cursor_clear_of_player, player_support
from verify_synchronized_scene import CAPACITY, SURFACE, TERRAIN_START


EAST_SURFACE_LAYOUT = "legacy-secondary-surface"
FULL_SURFACE_LAYOUT = "full-surface-raster"
FULL_SURFACE_CAMERA = (25, 21)
_PINK = b"\x86\x08\xf3"
_ORANGE = b"\0\x65\xff"
_MINIMAP_COLORS = {b"\x38\x71\x92": 11, b"\x82" * 3: 13}
_FULL_SURFACE_WITNESSES = (
    ((137, 25, 294, 40), "0f4a0259c4da8c3224c1d0dec8a6dd8879db07b7735a46c79c8e6c376b825d75"),
    ((192, 90, 222, 122), "edcf854aef011eaa4eea1143a6344e0ec0031a94457dbd46c976c0727ed2b946"),
)
_SOIL_BGR = ((4, 44, 85), (56, 113, 146))
_SOIL_BANDS = ((42, 126), (126, 210), (210, 294), (294, 377))


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
    if not cursor_clear_of_player(frame, center) or not player_support(frame, legacy_payload, observation)[0]:
        return None
    return observation


def _rgb_digest(raw, pitch, bounds):
    left, top, right, bottom = bounds
    native = b"".join(raw[y * pitch + left * 4:y * pitch + right * 4] for y in range(top, bottom))
    rgb = bytearray(len(native) // 4 * 3)
    for channel in range(3):
        rgb[channel::3] = native[2 - channel::4]
    return sha256(rgb).hexdigest()


def _dense_phase_soil(raw, pitch):
    """Require broad native checker coverage across the original Edit pane."""
    for top, bottom in _SOIL_BANDS:
        classified = 0
        for y in range(top, bottom):
            row = raw[y * pitch + 64 * 4:y * pitch + 416 * 4]
            for phase in (0, 1):
                expected = _SOIL_BGR[(y + phase) % 2]
                start = 4 * phase
                classified += sum(pixel == expected for pixel in zip(
                    row[start::8], row[start + 1::8], row[start + 2::8]
                ))
        if classified < 20000:
            return False
    return True


def verify_full_surface(frame, legacy_payload, legacy_observation, scent_mode):
    """Corroborate the observed adult Full Game emergence with native pixels."""
    if (scent_mode != 255 or legacy_observation.get("edit") != SURFACE
            or legacy_observation.get("map") != SURFACE
            or legacy_observation.get("views") != [SURFACE] * 3
            or len(legacy_payload) != CAPACITY):
        return None
    camera_x, camera_y = legacy_observation["camera"]
    ant_x, ant_y, ant_layer = legacy_observation["ant"]
    if (camera_x, camera_y) != FULL_SURFACE_CAMERA or ant_layer != SURFACE:
        return None
    if int.from_bytes(legacy_payload[PLAYER_HEADING:PLAYER_HEADING + 2], "little") != 2:
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None
    if not all(_rgb_digest(raw, pitch, bounds) == expected for bounds, expected in _FULL_SURFACE_WITNESSES):
        return None
    center = [71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)]
    observation = {
        **legacy_observation, "result": "accepted", "visible_ant": center,
        "terrain_layout": FULL_SURFACE_LAYOUT, "scent_mode": scent_mode,
    }
    if not cursor_clear_of_player(frame, center) or not player_support(frame, legacy_payload, observation)[0]:
        return None
    return observation if _dense_phase_soil(raw, pitch) else None
