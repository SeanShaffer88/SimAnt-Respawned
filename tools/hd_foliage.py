"""Shade the accent pixels of complete native Surface foliage sprites."""

from hashlib import sha256


# A cheap cyan witness precedes the exact row-major RGB hash.
_SHAPES = (
    (16, (9, 2), "1e8fb19331333042ec8a96b489ef77987629d63e7071331a57681b4b7428a9b8"),
    (32, (20, 3), "582cb3547b08a6d540965bd4b974ece95d15e7a9f6cf9971da95d652280cf9ee"),
)
_CYAN = b"\x00\xaa\xeb"
_CYAN_BGR = _CYAN[::-1]
_SOIL_BGR = (b"\x04\x2c\x55", b"\x38\x71\x92", b"\x10\x65\x00")
_DARK, _MID, _LIGHT = b"\x36\x51\x3c", b"\x60\x81\x59", b"\x87\xa5\x70"
_SHADES = {
    b"\x41" * 3: (_MID + _DARK, _DARK * 2),
    b"\x82" * 3: (_LIGHT + _MID, _MID + _DARK),
    _CYAN: (_LIGHT * 2, _LIGHT + _MID),
}


def _rgb_tile(raw, pitch, origin, size):
    native = b"".join(raw[origin + y * pitch:origin + y * pitch + 4 * size] for y in range(size))
    pixels = bytearray(3 * size * size)
    for channel in range(3):
        pixels[channel::3] = native[2 - channel::4]
    return pixels


def _matches(frame, edit_bounds):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < 4 * width or len(raw) < pitch * height:
        return
    left, top, right, bottom = edit_bounds
    first_x = left + 1 + (-(left + 1)) % 16
    first_y = top + 1 + (9 - (top + 1)) % 16
    for size, (seed_x, seed_y), signature in _SHAPES:
        witness = seed_y * pitch + 4 * seed_x
        ring = tuple(dy * pitch + 4 * dx for dy in range(-1, size + 1) for dx in range(-1, size + 1)
                     if dx in (-1, size) or dy in (-1, size))
        for y in range(first_y, bottom - size, 16):
            for x in range(first_x, right - size, 16):
                if x + size >= 400 and y + size >= 362:
                    continue  # The full sprite and ring must avoid the resize grip.
                origin = y * pitch + 4 * x
                seed = origin + witness
                if raw[seed:seed + 3] != _CYAN_BGR:
                    continue
                if not all(raw[origin + offset:origin + offset + 3] in _SOIL_BGR for offset in ring):
                    continue
                pixels = _rgb_tile(raw, pitch, origin, size)
                if sha256(pixels).hexdigest() == signature:
                    yield x, y, size, pixels


def paint_foliage(pixels, frame, edit_bounds):
    """Paint the verified foliage accents as four subpixels per native pixel."""
    stride = frame[0] * 6
    for x, y, size, rgb in _matches(frame, edit_bounds):
        origin = 2 * y * stride + x * 6
        for index in range(size * size):
            shade = _SHADES.get(bytes(rgb[3 * index:3 * index + 3]))
            if shade is not None:
                dy, dx = divmod(index, size)
                start = origin + 2 * dy * stride + dx * 6
                pixels[start:start + 6] = shade[0]
                pixels[start + stride:start + stride + 6] = shade[1]
