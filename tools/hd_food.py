"""Redraw the bright cells of complete native Surface food clusters."""


_CLUSTER = (
    "g.gggg..",
    ".gGGgGg.",
    "gGGGGgG.",
    "gGGGGGgg",
    "ggGGGgGg",
    "gGgGgGgg",
    ".gGgGgg.",
    "..gggg..",
)
_BRIGHT = b"\x14\xb6\x1c"
_DARK = b"\x10\x65\0"
_SOIL = (_DARK, b"\x04\x2c\x55", b"\x38\x71\x92")
_NATIVE = {"G": (_BRIGHT,), "g": (_DARK,), ".": _SOIL}
_SUPPORT = {(x, y) for y, row in enumerate(_CLUSTER) for x, role in enumerate(row) if role == "G"}

# The surrounding soil distinguishes a stationary cluster from a sprite or trail.
_WITNESSES = tuple(
    (x, y, _NATIVE[_CLUSTER[y][x]] if 0 <= x < 8 and 0 <= y < 8 else _SOIL)
    for y in range(-1, 9) for x in range(-1, 9)
)
_HIGHLIGHT = b"\x9e\xd7\x53"
_MIDTONE = b"\x82\xb2\x42"
_SHADOW = b"\x57\x7e\x29"


def _raster():
    """Keep the original bright silhouette with a one-subpixel lit edge."""
    support = {(2 * x + dx, 2 * y + dy) for x, y in _SUPPORT for dx in (0, 1) for dy in (0, 1)}
    pixels = []
    for x, y in sorted(support, key=lambda point: (point[1], point[0])):
        if (x + 1, y) not in support or (x, y + 1) not in support:
            color = _SHADOW
        elif (x - 1, y) not in support or (x, y - 1) not in support:
            color = _HIGHLIGHT
        else:
            color = _MIDTONE
        pixels.append((x, y, color))
    return tuple(pixels)


_RASTER = _raster()


def _food_origins(frame, edit_bounds):
    width, height, pitch, pixel_format, raw = frame
    if (width, height, pixel_format) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return
    left, top, right, bottom = edit_bounds
    first_x = left + 1 + (2 - (left + 1)) % 16
    first_y = top + 1 + (9 - (top + 1)) % 16
    witnesses = tuple((dy * pitch + dx * 4, colors) for dx, dy, colors in _WITNESSES)
    for y in range(first_y, bottom - 8, 16):
        for x in range(first_x, right - 8, 16):
            if x + 8 >= 400 and y + 8 >= 362:
                continue  # The full food and ring must avoid the resize grip.
            origin = y * pitch + x * 4
            seed = origin + pitch + 8  # The first bright cell is at (2, 1).
            if raw[seed:seed + 3] == _BRIGHT and all(
                raw[origin + offset:origin + offset + 3] in colors for offset, colors in witnesses
            ):
                yield x, y


def paint_food(pixels, frame, edit_bounds):
    """Paint only bright 2× subpixels from settled Surface food clusters."""
    stride = frame[0] * 6
    for x, y in _food_origins(frame, edit_bounds):
        origin = 2 * y * stride + x * 6
        for dx, dy, color in _RASTER:
            start = origin + dy * stride + dx * 3
            pixels[start:start + 3] = color
