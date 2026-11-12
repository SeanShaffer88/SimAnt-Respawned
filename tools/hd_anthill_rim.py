"""Shade the confirmed active Surface anthill without moving its entrance."""

from functools import cache
from hashlib import sha256

from hd_actors import EDIT_BOTTOM, EDIT_LEFT, EDIT_RIGHT, EDIT_TOP, NEIGHBORS, PLAYER_CENTER, PLAYER_WINDOW, _inside_edit
from hd_cursor import matched_cursor_raster
from verify_synchronized_scene import NEST, SURFACE


_RADIUS = 23
_SIDE = 47
_BLACK = b"\x00\x00\x00"
_GRAY = b"AAA"
_DARK = b"\x55\x2c\x04"
_LIGHT = b"\x92\x71\x38"
_STAMP_SHA256 = "045cad9ba8c57b3f17f3543134dce7fe51fb6ae012dba41f69ca29abfec19da4"
_RIM_SHA256 = "5fb0fec1813d7cbdd57c06ce33829e75492b26a0da7bf6d13380ed95afd1f0cb"
_SEEDS = tuple((x, y, _BLACK) for x, y in ((0, 0), (-5, 0), (6, 0), (3, -7))) + tuple(
    (x, y, _LIGHT[::-1]) for x, y in ((5, 5), (0, 8), (-6, -6))
)
_PIGMENTS = (
    (bytes((76, 46, 27)), bytes((132, 96, 53))),
    (bytes((107, 72, 39)), bytes((162, 125, 70))),
)


def _neighbors(points):
    return {(x + dx, y + dy) for x, y in points for dx, dy in NEIGHBORS
            if 0 <= x + dx < _SIDE and 0 <= y + dy < _SIDE}


@cache
def _rim_roles(stamp):
    # Called only after the exact stamp hash matches.
    def color(point):
        x, y = point
        start = 3 * (y * _SIDE + x)
        return stamp[start:start + 3]

    center = (_RADIUS, _RADIUS)
    core = {center}
    pending = [center]
    for point in pending:
        for neighbor in _neighbors((point,)) - core:
            if color(neighbor) in (_BLACK, _GRAY):
                core.add(neighbor)
                pending.append(neighbor)
    if len(core) != 143:
        return ()

    reached, frontier = core.copy(), core
    roles = {}
    for distance in (1, 2, 3):
        frontier = _neighbors(frontier) - reached
        reached.update(frontier)
        for point in frontier:
            native = color(point)
            if native in (_DARK, _LIGHT):
                roles[point] = distance, native == _LIGHT
    ordered = tuple((x, y, *roles[x, y]) for x, y in sorted(roles, key=lambda point: (point[1], point[0])))
    signature = bytes(value for x, y, _, light in ordered for value in (x, y, light))
    return ordered if len(ordered) == 196 and sha256(signature).hexdigest() == _RIM_SHA256 else ()


def _stamp(raw, pitch, left, top):
    native = b"".join(raw[y * pitch + left * 4:y * pitch + (left + _SIDE) * 4]
                      for y in range(top, top + _SIDE))
    rgb = bytearray(_SIDE * _SIDE * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = native[2::4], native[1::4], native[0::4]
    return bytes(rgb)


def _intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _matching_rim(frame, observation):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return None
    if (observation.get("result") != "accepted" or observation.get("edit") != SURFACE
            or observation.get("map") != SURFACE or observation.get("views") != [SURFACE] * 3):
        return None
    ant = observation.get("ant", ())
    camera = observation.get("camera", ())
    if len(ant) != 3 or len(camera) != 2:
        return None
    ant_x, ant_y, ant_layer = ant
    if ant_layer not in (SURFACE, NEST) or not 0 <= ant_x < 128 or not 0 <= ant_y < 64:
        return None
    actor = None
    if ant_layer == SURFACE:
        center = 71 + 16 * (ant_x - camera[0]), 49 + 16 * (ant_y - camera[1])
        visible_ant = observation.get("visible_ant")
        if visible_ant is not None and tuple(visible_ant) != center:
            return None
        x, y = center[0] - PLAYER_CENTER[0], center[1] - PLAYER_CENTER[1]
        actor = x, y, x + PLAYER_WINDOW[0], y + PLAYER_WINDOW[1]

    first_x = EDIT_LEFT + _RADIUS + (7 - EDIT_LEFT - _RADIUS) % 16
    first_y = EDIT_TOP + _RADIUS + (1 - EDIT_TOP - _RADIUS) % 16
    seeds = tuple((dy * pitch + 4 * dx, color) for dx, dy, color in _SEEDS)
    match = None
    for y in range(first_y, EDIT_BOTTOM - _RADIUS, 16):
        for x in range(first_x, EDIT_RIGHT - _RADIUS, 16):
            left, top = x - _RADIUS, y - _RADIUS
            if not _inside_edit(left, top, _SIDE, _SIDE):
                continue
            origin = y * pitch + 4 * x
            if any(raw[origin + offset:origin + offset + 3] != color for offset, color in seeds):
                continue
            stamp = _stamp(raw, pitch, left, top)
            if sha256(stamp).hexdigest() == _STAMP_SHA256:
                if match is not None:
                    return None
                match = left, top, stamp
    if match is None:
        return None
    left, top, stamp = match
    right, bottom = left + _SIDE, top + _SIDE
    if actor is not None and _intersects((left, top, right, bottom), actor):
        return None
    cursor = matched_cursor_raster(frame)
    if not cursor or any(2 * top <= row < 2 * bottom and 6 * left < start + len(rgb)
                         and start < 6 * right for row, start, rgb in cursor):
        return None
    return left, top, _rim_roles(stamp)


def paint_anthill_rim(pixels, frame, observation):
    """Repaint only the native soil cells within the authenticated rim."""
    match = _matching_rim(frame, observation)
    if match is None:
        return
    left, top, roles = match
    stride = frame[0] * 6
    for dx, dy, distance, light in roles:
        offset = 2 * (top + dy) * stride + 6 * (left + dx)
        if distance < 3:
            paint = _PIGMENTS[distance - 1][light] * 2
            pixels[offset:offset + 6] = paint
            pixels[offset + stride:offset + stride + 6] = paint
            continue
        pigment = _PIGMENTS[1][light]
        for row in (offset, offset + stride):
            for start in (row, row + 3):
                pixels[start:start + 3] = bytes((a + b) // 2 for a, b in zip(pixels[start:start + 3], pigment))
