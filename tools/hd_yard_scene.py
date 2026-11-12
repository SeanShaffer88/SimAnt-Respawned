"""Verify and repaint native lawn and siding in the original Full Game Yard."""

from functools import lru_cache
from hashlib import sha256
from struct import unpack_from

from hd_cursor import matched_cursor_raster
from hd_surface_scene import full_game_title_matches, native_rgb_digest
from hd_ui import MENU_BAR
from verify_synchronized_scene import SCALAR_START, TERRAIN_START


_CANVAS = (64, 83, 576, 339)
_BLINK = (443, 219, 490, 244)
_RAILS = ((62, 62), (576, 62), (577, 63), (577, 384), (62, 384), (576, 385), (63, 385))
_GOLD_BGR = bytes((4, 243, 255))
_TITLE_BGR = bytes((235, 170, 0))
_TITLE_PIXELS = ((284, 68), (328, 71), (344, 75))
_LAWN = bytes((28, 182, 20))
_SIDING = bytes((0, 0, 215))
_REGIONS = (
    (MENU_BAR, "1f782263a0bc107bfb3dbf9cf70b03c2feb1515e8632a606772c61756bb70689"),
    ((269, 63, 371, 82), "b66520cd38f8e8160a92b568a3e24582dd64538bf8d70a2610c44a7085c8ea49"),
    ((67, 341, 107, 383), "d9dfabed65810364210c1937f5402115f0f291c8634c1ad9a183c58fda34df48"),
    ((183, 43, 295, 56), "08376333727bb0a22f57eefd3d25a892aaac9b4fdb5f38e54799d40733b19785"),
)
_CANVAS_SHA = "a7cfcf2e7358cfff0b07a355a997a2b3aa7aa3888fc0fdb10267a2f0234e9613"
_BLINK_SHA = frozenset((
    "1c0ecf98efd95f91f54fefa407b8ae4052cf768f1e001d432c983c3d798f69c0",
    "6826e43ca063bb677eb05ec3f991088bf25cd9df9d25ed6b9b4187d317ae31a6",
    "771afb8d76050c1665b02e63b73a118d298a878a3cc7dec949561ec0fad3db16",
))
_SIDING_COMPONENTS = (
    ((237, 155), (138, 155, 238, 285), 2383, "7aba54255cbd494ed152f804a0efb9f88839ccd339257c8840bdef48761bf899"),
    ((316, 102), (274, 102, 317, 177), 1006, "7623f47a7febba64fc16642edda1225b8277989148932caefde6933cf5d2277f"),
)
_CURSOR_EXCLUSIONS = (MENU_BAR, (14, 22, 418, 63), (62, 62, 578, 386))


def _yard_state(scalars):
    if len(scalars) != TERRAIN_START or scalars[:3] != b"\0\0\1":
        return False

    def field(address):
        return unpack_from("<H", scalars, SCALAR_START + address - 0x515FC)[0]

    return tuple(field(address) for address in (0x51688, 0x5168A, 0x515FC, 0x5160A, 0x5160C)) == (25, 21, 37, 31, 1)


def yard_window_candidate(frame):
    """Reject ordinary frames before requesting an additional mailbox capture."""
    width, height, pitch, pixel_format, raw = frame
    if (width, height, pixel_format) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return False
    return all(raw[y * pitch + 4 * x:y * pitch + 4 * x + 3] == _TITLE_BGR for x, y in _TITLE_PIXELS)


def _cursor_clear(frame):
    cursor = matched_cursor_raster(frame)
    if not cursor:
        return False
    for row, offset, colors in cursor:
        for left, top, right, bottom in _CURSOR_EXCLUSIONS:
            if 2 * top <= row < 2 * bottom and offset < 6 * right and offset + len(colors) > 6 * left:
                return False
    return True


def _spans(y):
    left, _, right, _ = _CANVAS
    blink_left, blink_top, blink_right, blink_bottom = _BLINK
    if blink_top <= y < blink_bottom:
        return ((left, blink_left), (blink_right, right))
    return ((left, right),)


def _rgb(xrgb):
    rgb = bytearray(len(xrgb) // 4 * 3)
    for channel in range(3):
        rgb[channel::3] = xrgb[2 - channel::4]
    return bytes(rgb)


def _canvas_rgb(raw, pitch):
    return _rgb(b"".join(raw[y * pitch + 4 * left:y * pitch + 4 * right]
                         for y in range(_CANVAS[1], _CANVAS[3]) for left, right in _spans(y)))


def _blink_rgb(raw, pitch):
    left, top, right, bottom = _BLINK
    return _rgb(b"".join(raw[y * pitch + 4 * left:y * pitch + 4 * right] for y in range(top, bottom)))


def _siding_component(blue, seed, bounds, count, expected):
    if seed not in blue:
        return None
    queue = [seed]
    component = {seed}
    for x, y in queue:
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if neighbor in blue and neighbor not in component:
                component.add(neighbor)
                queue.append(neighbor)
    if len(component) != count:
        return None
    left, top, right, bottom = bounds
    if not all(left <= x < right and top <= y < bottom for x, y in component):
        return None
    points = bytes(offset for x, y in sorted(component, key=lambda point: (point[1], point[0]))
                   for offset in (x - left, y - top))
    return component if sha256(points).hexdigest() == expected else None


def _lawn_color(x, y):
    shade = (x // 13 * 5 + y // 7 * 3) % 7 - 3 + (x * 13 ^ y * 31) % 5 - 2
    return bytes((66 + shade, 134 + shade, 55 + shade))


def _siding_color(x, y):
    shade = (2, 1, 1, 0, 0, -1, -2, -3)[y % 8] + (x // 17 + y // 13) % 3 - 1
    return bytes((38 + shade, 74 + shade, 124 + shade))


def _paint_runs(points, shade):
    rows = []
    run = []

    def flush():
        left, y = run[0]
        for subrow in (0, 1):
            colors = b"".join(shade(2 * x + subcol, 2 * y + subrow) for x, _ in run for subcol in (0, 1))
            rows.append((2 * y + subrow, 6 * left, colors))

    for x, y in sorted(points, key=lambda point: (point[1], point[0])):
        if run and run[-1] != (x - 1, y):
            flush()
            run.clear()
        run.append((x, y))
    if run:
        flush()
    return tuple(rows)


@lru_cache(maxsize=1)
def _art_runs(canvas):
    lawn, blue = set(), set()
    offset = 0
    for y in range(_CANVAS[1], _CANVAS[3]):
        for left, right in _spans(y):
            for x in range(left, right):
                native = canvas[offset:offset + 3]
                if native == _LAWN:
                    lawn.add((x, y))
                elif native == _SIDING:
                    blue.add((x, y))
                offset += 3
    if len(lawn) != 36327 or not all(130 <= x <= 566 and 149 <= y <= 307 for x, y in lawn):
        return None
    siding = tuple(_siding_component(blue, *spec) for spec in _SIDING_COMPONENTS)
    if any(component is None for component in siding):
        return None
    return _paint_runs(lawn, _lawn_color) + _paint_runs(set.union(*siding), _siding_color)


@lru_cache(maxsize=len(_BLINK_SHA))
def _blink_lawn_runs(rgb):
    left, top, right, _ = _BLINK
    width = right - left
    points = ((left + index % width, top + index // width)
              for index in range(len(rgb) // 3) if rgb[index * 3:index * 3 + 3] == _LAWN)
    return _paint_runs(points, _lawn_color)


def verified_yard_runs(frame, scalars):
    """Return exact 2× paint runs for a matching Yard with synchronized state scalars."""
    if not _yard_state(scalars) or not yard_window_candidate(frame):
        return None
    _, _, pitch, _, raw = frame
    if not all(raw[y * pitch + 4 * x:y * pitch + 4 * x + 3] == _GOLD_BGR for x, y in _RAILS):
        return None
    if not full_game_title_matches(raw, pitch) or not _cursor_clear(frame):
        return None
    if any(native_rgb_digest(raw, pitch, bounds) != expected for bounds, expected in _REGIONS):
        return None
    blink = _blink_rgb(raw, pitch)
    if sha256(blink).hexdigest() not in _BLINK_SHA:
        return None
    canvas = _canvas_rgb(raw, pitch)
    if sha256(canvas).hexdigest() != _CANVAS_SHA:
        return None
    runs = _art_runs(canvas)
    return None if runs is None else runs + _blink_lawn_runs(blink)
