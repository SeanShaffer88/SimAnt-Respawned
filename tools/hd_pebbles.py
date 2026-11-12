"""Redraw verified neutral pixels in native Surface stone shapes."""

from functools import lru_cache
from hashlib import sha256

from hd_actors import NEIGHBORS, PLAYER_CENTER, PLAYER_WINDOW
from hd_cursor import matched_cursor_raster
from verify_synchronized_scene import SURFACE


_SOIL = (b"\x10\x65\0", b"\x04\x2c\x55", b"\x38\x71\x92")
_NATIVE = {"a": (b"\x41" * 3,), "b": (b"\x82" * 3,), "c": (b"\xc3" * 3,),
           "#": (b"\0" * 3,), ".": _SOIL}
_STONE = {
    "a": ((58, 54, 48), (73, 69, 62), (91, 88, 81)),
    "b": ((108, 104, 96), (131, 130, 122), (150, 153, 146)),
    "c": ((163, 160, 149), (188, 190, 180), (209, 215, 209)),
}
_PATTERNS = (
    (8, 12, ("bcc..", "cb..#", "#a###")),
    (4, 14, ("bcba#.", "cbbaa#", "ccc..#", ".c..##", ".####.")),
    (2, 0, ("bcba#.", "cbbaa#", "cccba#", ".cbba#", ".#a#a.")),
)


def _raster(shape):
    """Give each original gray cell four directional granite subpixels."""
    support = {(2 * x + dx, 2 * y + dy): _STONE[role]
               for y, row in enumerate(shape) for x, role in enumerate(row) if role in _STONE
               for dy in (0, 1) for dx in (0, 1)}
    raster = []
    for (x, y), shades in support.items():
        if (x + 1, y) not in support or (x, y + 1) not in support:
            shade = shades[0]
        elif (x - 1, y) not in support or (x, y - 1) not in support:
            shade = shades[2]
        else:
            shade = shades[1]
        grain = (x * 7 + y * 11) % 5 - 2
        raster.append((x, y, bytes(channel + grain for channel in shade)))
    return tuple(raster)


def _prepare(x_phase, y_phase, shape):
    width, height = len(shape[0]), len(shape)
    # Shadows match black and stay native. Dots and the full ring must be soil.
    witnesses = tuple(
        (x, y, _NATIVE[shape[y][x]] if 0 <= x < width and 0 <= y < height else _SOIL)
        for y in range(-1, height + 1) for x in range(-1, width + 1)
    )
    return x_phase, y_phase, width, height, witnesses, _raster(shape)


_PEBBLES = tuple(_prepare(*pattern) for pattern in _PATTERNS)
_SEED = _NATIVE["b"][0]  # Each native shape starts with a mid-gray pixel.
_BOULDER_WIDTH, _BOULDER_HEIGHT = 44, 46
_BOULDER_ROLES = "#abc"
_BOULDER_COLORS = {_NATIVE[role][0]: rank for rank, role in enumerate(_BOULDER_ROLES)}
_BOULDER_SEEDS = ((14, 0, 0), (10, 2, 1), (6, 5, 2), (10, 6, 3))
_BOULDER_SHA256 = "0007cdc09b03be5c0c1d24b7e475deeb563c7ee5751b4ce726a94d5ab29ba5c4"


def _matches(frame, edit_bounds):
    width, height, pitch, pixel_format, raw = frame
    if (width, height, pixel_format) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return
    left, top, right, bottom = edit_bounds
    for x_phase, y_phase, shape_width, shape_height, witnesses, raster in _PEBBLES:
        first_x = left + 1 + (x_phase - (left + 1)) % 16
        first_y = top + 1 + (y_phase - (top + 1)) % 16
        offsets = tuple((dy * pitch + dx * 4, colors) for dx, dy, colors in witnesses)
        for y in range(first_y, bottom - shape_height, 16):
            for x in range(first_x, right - shape_width, 16):
                if x + shape_width >= 400 and y + shape_height >= 362:
                    continue  # The full pebble and ring must avoid the resize grip.
                origin = y * pitch + x * 4
                if raw[origin:origin + 3] == _SEED and all(
                    raw[origin + offset:origin + offset + 3] in colors for offset, colors in offsets
                ):
                    yield x, y, raster


def _paint_matches(pixels, width, matches):
    stride = width * 6
    for x, y, raster in matches:
        origin = 2 * y * stride + x * 6
        for dx, dy, color in raster:
            start = origin + dy * stride + dx * 3
            pixels[start:start + 3] = color


def paint_pebbles(pixels, frame, edit_bounds):
    """Paint only the verified neutral support of each stationary pebble."""
    _paint_matches(pixels, frame[0], _matches(frame, edit_bounds))


@lru_cache(maxsize=1)
def _boulder_raster(shape):
    return _raster(shape)


def _boulder_component(raw, pitch, origin, blocked):
    """Flood only inside the fixed box, verifying each neighboring ring pixel."""
    seed = _BOULDER_SEEDS[0][:2]
    pending = [seed]
    component = {seed: 0}
    seen = {seed}
    ring = set()
    for x, y in pending:
        for dx, dy in NEIGHBORS:
            nx, ny = point = x + dx, y + dy
            if point in seen:
                continue
            seen.add(point)
            offset = origin + ny * pitch + nx * 4
            native = raw[offset:offset + 3]
            rank = _BOULDER_COLORS.get(native)
            if rank is None:
                if native not in _SOIL:
                    return None
                ring.add(point)
            else:
                if not (0 <= nx < _BOULDER_WIDTH and 0 <= ny < _BOULDER_HEIGHT):
                    return None
                component[point] = rank
                pending.append(point)
    if len(component) != 1433 or len(ring) != 190 or not blocked.isdisjoint(seen):
        return None
    ordered = sorted(component, key=lambda point: point[::-1])
    signature = bytes((_BOULDER_WIDTH, _BOULDER_HEIGHT)) + bytes(
        value for x, y in ordered for value in (x, y, component[x, y])
    )
    if sha256(signature).hexdigest() != _BOULDER_SHA256:
        return None
    return tuple("".join(_BOULDER_ROLES[component[x, y]] if (x, y) in component else "."
                         for x in range(_BOULDER_WIDTH)) for y in range(_BOULDER_HEIGHT))


def _boulder_matches(frame, observation, edit_bounds):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return
    cursor = matched_cursor_raster(frame)
    if not cursor:
        return
    blocked = {(x, y // 2) for y, start, colors in cursor[::2]
               for x in range(start // 6, (start + len(colors)) // 6)}
    ant_x, ant_y, layer = observation["ant"]
    if layer == SURFACE:
        camera_x, camera_y = observation["camera"]
        center = 71 + 16 * (ant_x - camera_x), 49 + 16 * (ant_y - camera_y)
        x0, y0 = (value - offset for value, offset in zip(center, PLAYER_CENTER))
        pose_width, pose_height = PLAYER_WINDOW
        blocked.update((x, y) for y in range(y0, y0 + pose_height) for x in range(x0, x0 + pose_width))

    left, top, right, bottom = edit_bounds
    first_x = left + 1 + (-(left + 1)) % 16
    first_y = top + 1 + (10 - (top + 1)) % 16
    seeds = tuple((dy * pitch + dx * 4, _NATIVE[_BOULDER_ROLES[rank]][0])
                  for dx, dy, rank in _BOULDER_SEEDS)
    for y in range(first_y, bottom - _BOULDER_HEIGHT, 16):
        for x in range(first_x, right - _BOULDER_WIDTH, 16):
            if x + _BOULDER_WIDTH >= 400 and y + _BOULDER_HEIGHT >= 362:
                continue  # The component and its full ring must avoid the resize grip.
            origin = y * pitch + x * 4
            if not all(raw[origin + offset:origin + offset + 3] == color for offset, color in seeds):
                continue
            relative_blocked = {(px - x, py - y) for px, py in blocked}
            shape = _boulder_component(raw, pitch, origin, relative_blocked)
            if shape is not None:
                yield x, y, _boulder_raster(shape)


def paint_boulders(pixels, frame, observation, edit_bounds):
    """Paint the gray support of the exact native Surface boulder."""
    _paint_matches(pixels, frame[0], _boulder_matches(frame, observation, edit_bounds))
