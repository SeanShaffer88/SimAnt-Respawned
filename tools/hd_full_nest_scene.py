"""Corroborate Full Game Black Nest terrain against the original raster."""

from functools import lru_cache
from struct import unpack_from

from hd_actors import (
    EDIT_LEFT, EDIT_RIGHT, PLAYER_CENTER, PLAYER_HEADING, PLAYER_WINDOW, cursor_clear_of_player, player_support,
)
from hd_cursor import matched_cursor_raster
from hd_surface_scene import full_game_title_matches, native_rgb_digest
from verify_synchronized_scene import CAPACITY, NEST, TERRAIN_START


FULL_BLACK_NEST_LAYOUT = "full-black-nest-first-buffer"
NEST_GRID_X, NEST_GRID_Y = 63, 41
NEST_PAINT_TOP, NEST_PAINT_BOTTOM = 57, 361
NEST_TERRAIN_BYTES = 64 * 64
_TILE_WIDTH = 16
_TILE_MASK = (1 << (8 * _TILE_WIDTH)) - 1
_MAP_BOUNDS = (418, 82, 576, 339)
_MAP_SHA256 = "562bbaa6d8c679221b036877b6cf3daa7a1105bd67aecd583b2d1a7a687b6c44"
_COLORS = ((4, 44, 85), (56, 113, 146), (130, 130, 130), (4, 243, 255))
_TABLES = {value: bytes(255 if candidate == value else 0 for candidate in range(256))
           for color in _COLORS for value in color}


def full_black_nest_camera(camera_x, camera_y):
    """Restrict this terrain witness to the measured shallow viewport."""
    return 0 <= camera_x <= 42 and camera_y == 0


def _palette_rows(raw, pitch):
    for y in range(NEST_PAINT_TOP, NEST_PAINT_BOTTOM):
        row = raw[y * pitch + 4 * EDIT_LEFT:y * pitch + 4 * EDIT_RIGHT]
        channels = row[::4], row[1::4], row[2::4]
        matches = []
        for color in _COLORS:
            blue, green, red = (int.from_bytes(channel.translate(_TABLES[value]), "little")
                                for channel, value in zip(channels, color))
            matches.append(blue & green & red)
        yield tuple(matches)


def _noncollinear(cells):
    x, y = cells[0]
    next_x, next_y = cells[1]
    return any((next_x - x) * (other_y - y) != (next_y - y) * (other_x - x)
               for other_x, other_y in cells[2:])


@lru_cache(maxsize=1)
def full_black_nest_raster(frame, terrain, camera, ant):
    """Return paired soil/floor row masks for the same verified native frame."""
    width, height, pitch, fmt, raw = frame
    if ((width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height
            or len(terrain) != NEST_TERRAIN_BYTES or not full_black_nest_camera(*camera)):
        return None
    rows = tuple(_palette_rows(raw, pitch))
    camera_x, camera_y = camera
    ant_x, ant_y = ant
    occupied = ant_x - camera_x, ant_y - camera_y
    soil_by_depth = [0, 0, 0, 0]
    floor_by_code = {12: 0, 15: 0}
    floor_cells, masks = [], []
    for y in range(1, 20):
        start = (y - 1) * _TILE_WIDTH
        block = rows[start:start + _TILE_WIDTH]
        soil_columns = floor_columns = 0
        for x in range(1, 22):
            if (x, y) == occupied:
                continue
            shift = 8 * (NEST_GRID_X - EDIT_LEFT + x * _TILE_WIDTH)
            columns = _TILE_MASK << shift
            dark, light, gray, gold = (sum((row[index] & columns).bit_count() for row in block) // 8
                                       for index in range(len(_COLORS)))
            if gold:
                continue
            code = terrain[(camera_y + y) * 64 + camera_x + x]
            if dark >= 190 and light <= 20 and gray <= 20:
                if code != 10:
                    return None
                soil_by_depth[(y - 1) // 5] += 1
                soil_columns |= columns
            elif light >= 45 and gray >= 45 and dark <= 90:
                if code not in floor_by_code:
                    return None
                floor_by_code[code] += 1
                floor_cells.append((x, y))
                floor_columns |= columns
        masks.extend((dark & soil_columns, light & floor_columns) for dark, light, _, _ in block)
    if (sum(soil_by_depth) < 350 or sum(count >= 60 for count in soil_by_depth) < 3 or len(floor_cells) < 5
            or min(floor_by_code.values()) < 2 or not _noncollinear(floor_cells)):
        return None

    def clear_span(y, left, right):
        left, right = max(EDIT_LEFT, left), min(EDIT_RIGHT, right)
        if left < right and NEST_PAINT_TOP <= y < NEST_PAINT_BOTTOM:
            keep = ~(((1 << (8 * (right - left))) - 1) << (8 * (left - EDIT_LEFT)))
            index = y - NEST_PAINT_TOP
            dark, light = masks[index]
            masks[index] = dark & keep, light & keep

    for y, left, rgb in matched_cursor_raster(frame)[::2]:
        clear_span(y // 2, left // 6, (left + len(rgb)) // 6)
    # Preserve any native shadow or outline in the complete projected pose window.
    center = _player_center(*occupied)
    width, height = PLAYER_WINDOW
    player_x, player_y = (value - offset for value, offset in zip(center, PLAYER_CENTER))
    for y in range(player_y, player_y + height):
        clear_span(y, player_x, player_x + width)
    return tuple(masks)


def _player_center(tile_x, tile_y):
    return 71 + 16 * tile_x, 49 + 16 * tile_y


def verify_full_black_nest(frame, payload, native, scent_mode):
    """Confirm the native pane, complete Yellow Ant pose, and first terrain span."""
    if (scent_mode != 255 or len(payload) != CAPACITY or native.get("result") != "terrain-unconfirmed"
            or native.get("edit") != NEST or native.get("map") != NEST or native.get("views") != [NEST] * 3):
        return None
    camera = tuple(native["camera"])
    ant_x, ant_y, layer = native["ant"]
    heading = unpack_from("<H", payload, PLAYER_HEADING)[0]
    if (not full_black_nest_camera(*camera) or layer != NEST or heading not in (2, 4, 6)
            or not 0 <= ant_x < 64 or not 0 <= ant_y < 64):
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None
    if not full_game_title_matches(raw, pitch) or native_rgb_digest(raw, pitch, _MAP_BOUNDS) != _MAP_SHA256:
        return None
    center = _player_center(ant_x - camera[0], ant_y - camera[1])
    observation = {**native, "result": "accepted", "visible_ant": list(center), "full_nest_pose": True,
                   "terrain_layout": FULL_BLACK_NEST_LAYOUT, "scent_mode": scent_mode}
    if not cursor_clear_of_player(frame, center) or not player_support(frame, payload, observation)[0]:
        return None
    terrain = payload[TERRAIN_START:TERRAIN_START + NEST_TERRAIN_BYTES]
    return observation if full_black_nest_raster(frame, terrain, camera, (ant_x, ant_y)) is not None else None
