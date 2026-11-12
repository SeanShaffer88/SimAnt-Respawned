"""Redraw the neutral pixels of complete native Surface pebble shapes."""


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


def paint_pebbles(pixels, frame, edit_bounds):
    """Paint only the verified neutral support of each stationary pebble."""
    stride = frame[0] * 6
    for x, y, raster in _matches(frame, edit_bounds):
        origin = 2 * y * stride + x * 6
        for dx, dy, color in raster:
            start = origin + dy * stride + dx * 3
            pixels[start:start + 3] = color
