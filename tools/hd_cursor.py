"""Redraw one complete native SimAnt arrow in a 2× presentation frame."""


_SHAPE = (
    "WWWWWWWWW",
    "WOYYYYYYW",
    "WYdddddYW",
    "WYdbdYYWW",
    "WYddbdYWW",
    "WYdYdbdYWW",
    "WYdYYdbdYWW",
    "WYYWWYdbdYWW",
    "WWWWWWYdbdYWW",
    ".....WWYdbdYW",
    "......WWYdbdW",
    ".......WWYdWW",
    "........WWWW",
)
_WIDTH = max(map(len, _SHAPE))
_HEIGHT = len(_SHAPE)
_NATIVE_BGR = {
    "W": b"\xff\xff\xff", "Y": b"\x04\xf3\xff", "d": b"\x41\x41\x41",
    "b": b"\0\0\0", "O": b"\0\x65\xff",
}
_ORANGE = _NATIVE_BGR["O"]
_SUPPORT = {
    (x, y): role for y, row in enumerate(_SHAPE)
    for x, role in enumerate(row) if role != "."
}
_SIGNATURE = tuple((x * 4, y, _NATIVE_BGR[role]) for (x, y), role in _SUPPORT.items())

# Each pair gives the upper and lower colors within one original pixel.
_SHADES = {
    "W": ((249, 252, 246), (214, 231, 228)),
    "Y": ((225, 239, 236), (190, 215, 213)),
    "d": ((76, 96, 105), (44, 63, 71)),
    "b": ((30, 43, 51), (20, 31, 38)),
    "O": ((255, 224, 143), (244, 170, 62)),
}
_OUTLINE = ((60, 78, 85), (26, 40, 47))


def _raster():
    """Build one opaque RGB run per row with a one-subpixel edge."""
    rows = []
    for y in range(2 * _HEIGHT):
        source = _SHAPE[y // 2]
        first = len(source) - len(source.lstrip("."))
        colors = bytearray()
        for x in range(2 * first, 2 * len(source)):
            role = source[x // 2]
            edge = any(
                ((x + dx) // 2, (y + dy) // 2) not in _SUPPORT
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
            )
            colors.extend((_OUTLINE if edge and role != "O" else _SHADES[role])[y % 2])
        rows.append((first * 6, bytes(colors)))
    return tuple(rows)


_RASTER = _raster()


def _cursor_origin(frame):
    width, height, pitch, pixel_format, raw = frame
    if pixel_format != 1 or width < _WIDTH or height < _HEIGHT or pitch < width * 4:
        return None
    end = pitch * height
    if len(raw) < end:
        return None

    found = None
    seed = raw.find(_ORANGE, 0, end)
    while seed != -1:
        seed_y, column = divmod(seed, pitch)
        x, y = column // 4 - 1, seed_y - 1
        if column % 4 == 0 and 0 <= x <= width - _WIDTH and 0 <= y <= height - _HEIGHT:
            origin = y * pitch + x * 4
            if all(raw[origin + dy * pitch + dx:origin + dy * pitch + dx + 3] == bgr
                   for dx, dy, bgr in _SIGNATURE):
                if found is not None:
                    return None
                found = (x, y)
        seed = raw.find(_ORANGE, seed + 1, end)
    return found


def matched_cursor_raster(frame):
    """Return (2× row, RGB byte offset, RGB bytes) for a verified cursor."""
    origin = _cursor_origin(frame)
    if origin is None:
        return ()
    x, y = origin
    return tuple((2 * y + row, 6 * x + left, rgb) for row, (left, rgb) in enumerate(_RASTER))


def paint_cursor(pixels, frame):
    """Paint only the opaque support of a unique, full native arrow."""
    row_size = frame[0] * 6
    for row, left, rgb in matched_cursor_raster(frame):
        start = row * row_size + left
        pixels[start:start + len(rgb)] = rgb
