"""Corroborate additional Surface scenes with the native framebuffer."""

from hashlib import sha256

from hd_actors import (
    EDIT_BOTTOM, EDIT_LEFT, EDIT_RIGHT, EDIT_TOP, GOLD_BGR, PLAYER_CENTER, PLAYER_HEADING, PLAYER_WINDOW,
    cursor_clear_of_player, forage_player_support, player_support,
)
from hd_cursor import matched_cursor_raster
from verify_synchronized_scene import CAPACITY, SURFACE, TERRAIN_START


EAST_SURFACE_LAYOUT = "legacy-secondary-surface"
FULL_SURFACE_LAYOUT = "full-surface-raster"
FULL_PANNED_SURFACE_LAYOUT = "full-surface-first-buffer"
FULL_SURFACE_CAMERA = (25, 21)
_FORAGE_CAMERA = (45, 14)
_PINK = b"\x86\x08\xf3"
_ORANGE = b"\0\x65\xff"
_MINIMAP_COLORS = {b"\x38\x71\x92": 11, b"\x82" * 3: 13}
_FULL_SURFACE_TITLE = ((137, 25, 294, 40), "0f4a0259c4da8c3224c1d0dec8a6dd8879db07b7735a46c79c8e6c376b825d75")
_FULL_SURFACE_LANDMARKS = {
    FULL_SURFACE_CAMERA: ((192, 90, 222, 122), "edcf854aef011eaa4eea1143a6344e0ec0031a94457dbd46c976c0727ed2b946"),
    _FORAGE_CAMERA: ((142, 145, 194, 194), "99e469ad9688888a78aa542193a09785b3119c683abee8d837f9d0afd022a312"),
    (25, 20): ((192, 106, 222, 138), "edcf854aef011eaa4eea1143a6344e0ec0031a94457dbd46c976c0727ed2b946"),
}
FULL_SURFACE_CAMERAS = frozenset(_FULL_SURFACE_LANDMARKS)
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
    """Corroborate adult Full Game emergence and forage with native pixels."""
    if (scent_mode != 255 or legacy_observation.get("edit") != SURFACE
            or legacy_observation.get("map") != SURFACE
            or legacy_observation.get("views") != [SURFACE] * 3
            or len(legacy_payload) != CAPACITY):
        return None
    camera = tuple(legacy_observation["camera"])
    camera_x, camera_y = camera
    ant_x, ant_y, ant_layer = legacy_observation["ant"]
    landmark = _FULL_SURFACE_LANDMARKS.get(camera)
    if landmark is None or ant_layer != SURFACE:
        return None
    heading = int.from_bytes(legacy_payload[PLAYER_HEADING:PLAYER_HEADING + 2], "little")
    panned_forage = camera == _FORAGE_CAMERA
    if not panned_forage and heading != (2 if camera == FULL_SURFACE_CAMERA else 6):
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None
    if not all(_rgb_digest(raw, pitch, bounds) == expected for bounds, expected in (_FULL_SURFACE_TITLE, landmark)):
        return None
    center = [71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)]
    observation = {
        **legacy_observation, "result": "accepted", "visible_ant": center,
        "terrain_layout": FULL_SURFACE_LAYOUT, "scent_mode": scent_mode,
    }
    if not cursor_clear_of_player(frame, center):
        return None
    if panned_forage:
        if not forage_player_support(frame, legacy_payload, observation)[0]:
            return None
        observation["full_forage_pose"] = True
    elif not player_support(frame, legacy_payload, observation)[0]:
        return None
    return observation if _dense_phase_soil(raw, pitch) else None

# The Edit grid begins two pixels left of its visible terrain. Use only
# complete cells above the resize grip and a fixed, visible part of Map.
_EDIT_TILE_X = 62
_GRAY_BGR = tuple((value,) * 3 for value in (65, 130, 195))
_PIXEL_MATCH = {value: bytes(int(index == value) for index in range(256))
                for color in (*_SOIL_BGR, *_GRAY_BGR) for value in color}


def full_surface_camera(camera_x, camera_y):
    """Require the original 22×21 Edit viewport to fit the 128×64 yard."""
    return 0 <= camera_x <= 106 and 0 <= camera_y <= 43


def _full_map_matches(raw, pitch, terrain):
    """Check classified native cells in the exposed right Map slice."""
    for start in range(0, 64, 16):
        classified = rocks = 0
        for y in range(start, start + 16):
            row = (84 + 4 * y) * pitch
            for x in range(88, 128):
                offset = row + 4 * (418 + 4 * (x - 88))
                code = _MINIMAP_COLORS.get(raw[offset:offset + 3])
                if code is not None:
                    if terrain[y * 128 + x] != code:
                        return False
                    classified += 1
                    rocks += code == 13
        if classified < 600 or rocks < 16:
            return False
    return True


def _pixel_flags(channels, colors):
    """Build a byte per pixel from exact BGR triples."""
    mask = 0
    for color in colors:
        blue, green, red = (int.from_bytes(data.translate(_PIXEL_MATCH[value]), "little")
                            for data, value in zip(channels, color))
        mask |= blue & green & red
    return mask.to_bytes(len(channels[0]), "little")


def _full_edit_samples(raw, pitch):
    """Find phase-locked soil and distributed gray pixels in complete tiles."""
    left, top, right, bottom = EDIT_LEFT, EDIT_TOP, EDIT_RIGHT, EDIT_BOTTOM
    width = right - left
    rows = b"".join(raw[y * pitch + 4 * left:y * pitch + 4 * right] for y in range(top, bottom))
    channels = tuple(rows[channel::4] for channel in range(3))
    dark = _pixel_flags(channels, _SOIL_BGR[:1])
    light = _pixel_flags(channels, _SOIL_BGR[1:])
    gray = _pixel_flags(channels, _GRAY_BGR)
    mark = b"\x01"
    for band_top, band_bottom in _SOIL_BANDS:
        phased = 0
        for y in range(band_top, band_bottom):
            start = (y - top) * width
            end = start + width
            phase = y % 2
            phased += dark[start + phase:end:2].count(mark)
            phased += light[start + 1 - phase:end:2].count(mark)
        if phased < 20000:
            return (), ()

    soil = (int.from_bytes(dark, "little") | int.from_bytes(light, "little")).to_bytes(len(dark), "little")
    rock_cells, soil_cells = [], []
    for y in range(1, 20):
        tile_top = y * 16 * width
        for x in range(1, 21):
            start = tile_top + _EDIT_TILE_X + x * 16 - left
            offsets = range(start, start + 16 * width, width)
            if sum(soil[offset:offset + 16].count(mark) for offset in offsets) >= 210:
                soil_cells.append((x, y))
            if sum(gray[offset:offset + 16].count(mark) for offset in offsets) < 70:
                continue
            quadrants = (
                sum(gray[offset + column:offset + column + 8].count(mark) for offset in offsets[row:row + 8])
                for row in (0, 8) for column in (0, 8)
            )
            if sum(count >= 10 for count in quadrants) >= 3:
                rock_cells.append((x, y))
    return rock_cells, soil_cells


def _full_edit_matches(raw, pitch, terrain, camera):
    rocks, soil = _full_edit_samples(raw, pitch)
    if len(rocks) < 10 or len(soil) < 100:
        return False

    def match(corner, cells, code):
        cx, cy = corner
        return sum(terrain[(cy + y) * 128 + cx + x] == code for x, y in cells)

    if match(camera, rocks, 13) != len(rocks) or match(camera, soil, 11) * 100 < len(soil) * 95:
        return False
    cx, cy = camera
    # A near-alias must not be equally credible when the ant is offscreen.
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            alternate = cx + dx, cy + dy
            if (dx or dy) and full_surface_camera(*alternate) and match(alternate, rocks, 13) > len(rocks) - 3:
                return False
    return True


def _offscreen_player(frame, center):
    x, y = center[0] - PLAYER_CENTER[0], center[1] - PLAYER_CENTER[1]
    width, height = PLAYER_WINDOW
    if not (x + width <= EDIT_LEFT or x >= EDIT_RIGHT or y + height <= EDIT_TOP or y >= EDIT_BOTTOM):
        return False
    cursor = matched_cursor_raster(frame)
    if not cursor:
        return False
    cursor_runs = {row // 2: (start // 6, (start + len(rgb)) // 6)
                   for row, start, rgb in cursor[::2]}
    _, _, pitch, _, raw = frame
    for y in range(EDIT_TOP, EDIT_BOTTOM):
        row = y * pitch
        offset = raw.find(GOLD_BGR, row + 4 * EDIT_LEFT, row + 4 * EDIT_RIGHT)
        while offset != -1:
            x, phase = divmod(offset - row, 4)
            cursor_left, cursor_right = cursor_runs.get(y, (0, 0))
            if not phase and not cursor_left <= x < cursor_right:
                return False
            offset = raw.find(GOLD_BGR, offset + 1, row + 4 * EDIT_RIGHT)
    return True


def verify_panned_full_surface(frame, legacy_payload, observation, scent_mode, terrain):
    """Corroborate Full Game's first terrain buffer against both native panes."""
    if (scent_mode != 255 or observation.get("edit") != SURFACE
            or observation.get("map") != SURFACE or observation.get("views") != [SURFACE] * 3
            or len(legacy_payload) != CAPACITY or len(terrain) != 8192):
        return None
    camera = tuple(observation["camera"])
    ant_x, ant_y, ant_layer = observation["ant"]
    if (not full_surface_camera(*camera) or ant_layer != SURFACE
            or not 0 <= ant_x < 128 or not 0 <= ant_y < 64):
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return None
    title, expected = _FULL_SURFACE_TITLE
    if _rgb_digest(raw, pitch, title) != expected:
        return None

    # The independent Full Game terrain span comes from 0x6E430.
    if not _full_map_matches(raw, pitch, terrain):
        return None
    camera_x, camera_y = camera
    center = [71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)]
    verified = {**observation, "result": "accepted", "terrain_layout": FULL_PANNED_SURFACE_LAYOUT,
                "scent_mode": scent_mode}
    if not _offscreen_player(frame, center):
        verified["visible_ant"] = center
        if not cursor_clear_of_player(frame, center):
            return None
        if not player_support(frame, legacy_payload, verified)[0]:
            if not forage_player_support(frame, legacy_payload, verified)[0]:
                return None
            verified["full_forage_pose"] = True

    return verified if _full_edit_matches(raw, pitch, terrain, camera) else None
