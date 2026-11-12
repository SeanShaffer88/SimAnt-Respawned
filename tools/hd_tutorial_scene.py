"""Verify the first Tutorial dig against both captured native tile spans."""

from functools import lru_cache
from struct import unpack_from

from hd_actors import GOLD_BGR, PLAYER_HEADING, cursor_clear_of_player, player_support
from hd_cursor import matched_cursor_raster
from hd_full_nest_scene import NEST_GRID_X, NEST_GRID_Y, exclude_nest_footprints, nest_palette_rows, noncollinear_tiles
from hd_surface_scene import native_rgb_digest
from verify_synchronized_scene import CAPACITY, NEST, TERRAIN_START


TUTORIAL_NEST_LAYOUT = "tutorial-nest-truncated-buffers"
TUTORIAL_CAMERA = (20, 0)
TUTORIAL_BOUNDS = (79, 89, 623, 473)
_TITLE_BOUNDS = (225, 25, 411, 40)
_TITLE_SHA256 = "583be0378c73158a6d818185d3de1601a689a8937c080b979609ee55feb9156c"
_GOLD_RAILS = ((14, 22), (14, 474), (625, 22), (625, 474), (624, 440), (63, 473))
_BLACK_BUTTON = ((21, 119), (23, 122), (35, 123))
_BLACK_BUTTON_BGR = b"\xa6\x00\x45"
_MODAL_RUNS = tuple(bytes((tone,)) * 40 for tone in (0, 130, 195, 255))
_TILE_SIZE = 16
_TILE_MASK = (1 << (8 * _TILE_SIZE)) - 1
_INNER_COLUMNS = ((1 << (8 * (TUTORIAL_BOUNDS[2] - TUTORIAL_BOUNDS[0] - 2))) - 1) << 8
_TERRAIN_BYTES = 64 * 64
_CANONICAL_TILE_BYTES = 8192
# The loaded-layout union starts after the Tutorial's logical tile zero:
# 0x6E400 - 0x6E380 and 0x83DE0 - 0x83D10, respectively.
_OMITTED = (128, 208)


def _modal_open(raw, pitch):
    for y in range(42, 473):
        row = raw[y * pitch + 63 * 4:y * pitch + 624 * 4]
        blue, green, red = row[::4], row[1::4], row[2::4]
        for run in _MODAL_RUNS:
            start = blue.find(run)
            while start != -1:
                if green.startswith(run, start) and red.startswith(run, start):
                    return True
                start = blue.find(run, start + 1)
    return False


def _terrain_spans(payload):
    starts = (TERRAIN_START, TERRAIN_START + _CANONICAL_TILE_BYTES)
    return tuple(payload[start:start + _TERRAIN_BYTES - omitted] for start, omitted in zip(starts, _OMITTED))


def _cursor_rows(frame):
    left, top, right, bottom = TUTORIAL_BOUNDS
    rows = [0] * (bottom - top)
    for row, offset, rgb in matched_cursor_raster(frame)[::2]:
        y = row // 2
        start = max(left, offset // 6)
        end = min(right, (offset + len(rgb)) // 6)
        if top <= y < bottom and start < end:
            rows[y - top] = ((1 << (8 * (end - start))) - 1) << (8 * (start - left))
    return rows


def _seam_soil(above, row, below):
    dark, light, gray, _ = row
    left, right = dark << 8, dark >> 8
    up, down = above[0], below[0]
    three_neighbors = (left & right & (up | down)) | (up & down & (left | right))
    wall = above[1] | above[2] | light | gray | below[1] | below[2]
    return dark & three_neighbors & ~(wall | (wall << 8) | (wall >> 8)) & _INNER_COLUMNS


@lru_cache(maxsize=1)
def _tutorial_raster(frame, first, second, ant):
    if (len(first), len(second)) != tuple(_TERRAIN_BYTES - n for n in _OMITTED):
        return None
    _, _, pitch, _, raw = frame
    rows = tuple(nest_palette_rows(raw, pitch, TUTORIAL_BOUNDS))
    cursor_rows = _cursor_rows(frame)
    camera_x, camera_y = TUTORIAL_CAMERA
    occupied = ant[0] - camera_x, ant[1] - camera_y
    soil_by_depth = [0] * 5
    floor_cells, masks, seam_columns_by_row = [], [], []
    code_15 = 0
    for y in range(3, 27):
        start = (y - 3) * _TILE_SIZE
        block = rows[start:start + _TILE_SIZE]
        cursor_block = cursor_rows[start:start + _TILE_SIZE]
        soil_columns = floor_columns = seam_columns = 0
        for x in range(1, 35):
            if (x, y) == occupied or (x, y) == (34, 26):
                continue
            columns = _TILE_MASK << (8 * _TILE_SIZE * (x - 1))
            dark, light, gray, gold = (sum((row[index] & columns).bit_count() for row in block) // 8
                                       for index in range(4))
            cell = (camera_y + y) * 64 + camera_x + x
            first_index, second_index = (cell - omitted for omitted in _OMITTED)
            if not 0 <= first_index < len(first) or not 0 <= second_index < len(second):
                return None
            code, other = first[first_index], second[second_index]
            if code == other == 10 and (not gold or all(
                not (row[3] & columns & ~cursor)
                for row, cursor in zip(block, cursor_block)
            )):
                seam_columns |= columns
            # Cursor coverage does not add any terrain proof to the original gate.
            if gold:
                continue
            if dark >= 190 and light <= 20 and gray <= 20:
                if code != 10 or other != code:
                    return None
                soil_by_depth[(y - 3) // 5] += 1
                soil_columns |= columns
            elif light >= 45 and gray >= 45 and dark <= 90:
                if code not in (12, 15) or other != code:
                    return None
                code_15 += code == 15
                floor_cells.append((x, y))
                floor_columns |= columns
        masks.extend((dark & soil_columns, light & floor_columns) for dark, light, _, _ in block)
        seam_columns_by_row.append(seam_columns)
    if (sum(soil_by_depth) < 760 or sum(count >= 100 for count in soil_by_depth) < 4
            or len(floor_cells) < 8 or code_15 < 2 or not noncollinear_tiles(floor_cells)):
        return None
    # Add only native dark interiors after the frame passes the existing proof.
    for y, (above, row, below) in enumerate(zip(rows, rows[1:], rows[2:]), 1):
        soil, floor = masks[y]
        supplemental = _seam_soil(above, row, below) & seam_columns_by_row[y // _TILE_SIZE]
        masks[y] = soil | supplemental, floor
    center = 71 + 16 * occupied[0], 49 + 16 * occupied[1]
    exclude_nest_footprints(frame, masks, TUTORIAL_BOUNDS, center)
    return tuple(masks)


def tutorial_nest_raster(frame, payload, ant):
    """Reuse masks derived from the two verified truncated spans."""
    return _tutorial_raster(frame, *_terrain_spans(payload), ant)


def verify_tutorial_nest(frame, payload, native, scent_mode):
    """Require a clear maximized Tutorial pane and its native terrain witnesses."""
    if (scent_mode != 255 or len(payload) != CAPACITY or native.get("edit") != NEST
            or native.get("map") is not None or native.get("views") != [NEST] * 3
            or tuple(native["camera"]) != TUTORIAL_CAMERA
            or unpack_from("<H", payload, PLAYER_HEADING)[0] != 2):
        return None
    ant_x, ant_y, layer = native["ant"]
    if layer != NEST or not 0 <= ant_x < 64 or not 0 <= ant_y < 64:
        return None
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None

    def pixel(x, y):
        start = y * pitch + 4 * x
        return raw[start:start + 3]

    if (native_rgb_digest(raw, pitch, _TITLE_BOUNDS) != _TITLE_SHA256
            or not all(pixel(x, y) == GOLD_BGR for x, y in _GOLD_RAILS)
            or not all(pixel(x, y) == _BLACK_BUTTON_BGR for x, y in _BLACK_BUTTON)
            or _modal_open(raw, pitch)):
        return None
    center = 71 + 16 * (ant_x - TUTORIAL_CAMERA[0]), 49 + 16 * (ant_y - TUTORIAL_CAMERA[1])
    accepted = {**native, "result": "accepted", "visible_ant": list(center), "terrain_layout": TUTORIAL_NEST_LAYOUT,
                "scent_mode": scent_mode}
    if not cursor_clear_of_player(frame, center) or len(player_support(frame, payload, accepted)[0]) != 11:
        return None
    return accepted if tutorial_nest_raster(frame, payload, (ant_x, ant_y)) is not None else None
