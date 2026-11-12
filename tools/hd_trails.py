"""HD treatment for complete native pheromone trail tiles."""

from functools import cache


SCENT_MODE_OFFSET = 0x3DF4E
BLACK_TRAIL = 2
_RGB = {"r": (223, 8, 4), "o": (255, 101, 0), "y": (255, 243, 4)}
# Only these complete DOS dithers have been observed. Partial stencils may
# contain a sprite, cursor, or overlay and must retain all their original pixels.
_STENCILS = (("roro", "oror"), ("oroo", "ooor"), ("yoyy", "yyyo"))


def _source_row(pattern):
    pixels = [_RGB[key] for key in pattern * 4]
    return tuple(bytes(pixel[channel] for pixel in pixels) for channel in (2, 1, 0))


_FIRST_ROWS = {_source_row(first): (index, _source_row(second))
               for index, (first, second) in enumerate(_STENCILS)}


def _tile_row(raw, pitch, x, y):
    begin = y * pitch + 4 * x
    return tuple(raw[begin + channel:begin + 64:4] for channel in range(3))


def trail_tiles(frame, mode):
    """Return (left, top, visual tier) for complete tiles in a settled scent view."""
    width, height, pitch, fmt, raw = frame
    if mode != BLACK_TRAIL or (width, height, fmt) != (640, 480, 1):
        return ()
    if pitch < width * 4 or len(raw) < pitch * height:
        return ()
    # The original control remains the final corroboration of the selected
    # mode. Off can leave stale colored tiles on screen during a redraw.
    for x, y, rgb in ((23, 189, (223, 8, 4)), (25, 190, (255, 255, 255))):
        begin = y * pitch + 4 * x
        if raw[begin:begin + 3] != bytes(rgb[::-1]):
            return ()
    tiles = []
    # DOS draws the full trail tiles on a 16 px grid. Avoid partial top and
    # bottom tiles and the original resize grip in the lower-right corner.
    for y in range(57, 362, 16):
        for x in range(64, 401, 16):
            if x >= 400 and y >= 345:
                continue
            first = _tile_row(raw, pitch, x, y)
            match = _FIRST_ROWS.get(first)
            if match is None:
                continue
            tier, second = match
            if all(_tile_row(raw, pitch, x, y + row) == (second if row % 2 else first)
                   for row in range(1, 16)):
                tiles.append((x, y, tier))
    return tuple(tiles)


@cache
def _trail_raster(tier):
    """Render a quiet tint with one, two, or three centered trail marks."""
    base = (36, 68, 63)
    marker = bytes((132, 229, 203))
    background = tuple(value + tier * 9 for value in base)
    rows = [bytearray(bytes(background) * 32) for _ in range(32)]
    count = tier + 1
    first = 16 - count * 4 + 1
    for left in range(first, first + count * 8, 8):
        for y in (14, 15, 16, 17):
            row = rows[y]
            for x in range(left, left + 6):
                if x in (left, left + 5) and y in (14, 17):
                    continue
                row[x * 3:x * 3 + 3] = marker
    return tuple(bytes(row) for row in rows)


def _paint_tiles(pixels, row_size, tiles):
    for x, y, tier in tiles:
        offset = 2 * y * row_size + x * 6
        for row in _trail_raster(tier):
            pixels[offset:offset + len(row)] = row
            offset += row_size


def paint_trails(pixels, frame, mode):
    """Repaint verified tiles in a writable 2× RGB frame."""
    tiles = trail_tiles(frame, mode)
    if tiles:
        _paint_tiles(pixels, frame[0] * 6, tiles)
    return len(tiles)


def render_trails(frame, mode):
    """Return a 2× PPM with verified scent tiles redrawn, or None for native fallback."""
    tiles = trail_tiles(frame, mode)
    if not tiles:
        return None
    width, height, pitch, _, raw = frame
    row_size = width * 6
    pixels = bytearray(row_size * height * 2)
    for y in range(height):
        begin = y * pitch
        source = raw[begin:begin + width * 4]
        row = bytearray(row_size)
        for channel in range(3):
            color = source[2 - channel::4]
            row[channel::6] = row[channel + 3::6] = color
        offset = 2 * y * row_size
        pixels[offset:offset + 2 * row_size] = row + row
    _paint_tiles(pixels, row_size, tiles)
    return f"P6\n{width * 2} {height * 2}\n255\n".encode("ascii") + pixels
