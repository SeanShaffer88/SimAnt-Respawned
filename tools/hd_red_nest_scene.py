"""Confirm native soil and tunnel pixels in the occupied Red Nest."""

from functools import lru_cache
from struct import unpack_from

from hd_actors import PLAYER_HEADING, cursor_clear_of_player, player_support
from verify_synchronized_scene import CAPACITY, NEST, RED_NEST


OCCUPIED_RED_LAYOUT = "occupied-red-raster"
OCCUPIED_RED_CAMERA = (21, 0)
LEFT, RIGHT = 64, 416
TOP, BOTTOM = 57, 361
_COLUMNS = RIGHT - LEFT
_INNER_COLUMNS = ((1 << ((_COLUMNS - 2) * 8)) - 1) << 8
_ODD_COLUMNS = int.from_bytes(b"\x00\xff" * (_COLUMNS // 2), "little")
_COLORS = ((4, 44, 85), (56, 113, 146), (65, 65, 65), (130, 130, 130))
_TABLES = {
    value: bytes(255 if candidate == value else 0 for candidate in range(256))
    for color in _COLORS for value in color
}


def _row_palettes(raw, pitch, y):
    row = raw[y * pitch + 4 * LEFT:y * pitch + 4 * RIGHT]
    channels = row[::4], row[1::4], row[2::4]
    matches = []
    for color in _COLORS:
        blue, green, red = (int.from_bytes(channel.translate(_TABLES[value]), "little")
                            for channel, value in zip(channels, color))
        matches.append(blue & green & red)
    dark, light, gray65, gray130 = matches
    return dark, light, gray130, dark | light | gray65 | gray130


def _three_neighbors(row, above, below):
    left, right = row << 8, row >> 8
    return (left & right & (above | below)) | (above & below & (left | right))


def _allowed_ring(row, above, below):
    return ((row << 8) & (row >> 8)
            & (above << 8) & above & (above >> 8)
            & (below << 8) & below & (below >> 8))


# Verification and rendering reuse the same immutable captured frame.
@lru_cache(maxsize=1)
def occupied_red_raster(frame):
    """Return 352-column byte masks for Edit rows 57–360 after tunnel confirmation."""
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return None
    rows = [_row_palettes(raw, pitch, y) for y in range(TOP - 1, BOTTOM + 1)]
    masks = []
    confirmed_light = 0
    for y, (above, center, below) in enumerate(zip(rows, rows[1:], rows[2:]), TOP):
        dark, light, gray, allowed = center
        earth = dark & _three_neighbors(dark, above[0], below[0]) & _INNER_COLUMNS
        phase = ~_ODD_COLUMNS if y % 2 else _ODD_COLUMNS
        tunnel = (light & phase & _three_neighbors(gray, above[2], below[2])
                  & _allowed_ring(allowed, above[3], below[3]) & _INNER_COLUMNS)
        confirmed_light += tunnel.bit_count() // 8
        masks.append((earth, tunnel))
    return tuple(masks) if confirmed_light >= 1200 else None


def verify_occupied_red(frame, payload, native, scent_mode):
    """Verify the observed Red Nest entry without relying on unmatched terrain copies."""
    if (scent_mode != 255 or len(payload) != CAPACITY
            or native.get("edit") != RED_NEST or native.get("map") != NEST
            or native.get("views") != [RED_NEST] * 3
            or tuple(native["camera"]) != OCCUPIED_RED_CAMERA):
        return None
    ant_x, ant_y, ant_layer = native["ant"]
    if (ant_layer != RED_NEST or not 0 <= ant_x < 64 or not 0 <= ant_y < 64
            or unpack_from("<H", payload, PLAYER_HEADING)[0] != 4):
        return None
    camera_x, camera_y = OCCUPIED_RED_CAMERA
    center = [71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)]
    observation = {
        **native, "result": "accepted", "visible_ant": center,
        "terrain_layout": OCCUPIED_RED_LAYOUT, "scent_mode": scent_mode,
    }
    if (not cursor_clear_of_player(frame, center) or not player_support(frame, payload, observation)[0]
            or occupied_red_raster(frame) is None):
        return None
    return observation
