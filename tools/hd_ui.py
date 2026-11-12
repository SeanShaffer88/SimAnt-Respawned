"""Repaint verified, resting DOS controls inside their original bounds."""

from functools import cache
from hashlib import sha256


# Exact native RGB fingerprints bind each skin to the pinned DOS view and state.
MENU_BAR = (0, 0, 640, 16)
REGIONS = (
    (MENU_BAR, "1f782263a0bc107bfb3dbf9cf70b03c2feb1515e8632a606772c61756bb70689"),
    ((18, 42, 62, 58), "d2a93e2253646209936ce7efab25cb754f7ee96a920e610dafc903cdff3d2df7"),  # Map
    ((18, 60, 39, 83), "0a517cbdaee2040534bb00277ad846744d37d27267d774d40c64e66b2bc01a0d"),  # Help
    ((40, 60, 62, 83), "f736c1d50b59f451a08ad9edddf4703ba60af1fa4387bedf47d03c5c783a028a"),  # Utility
    ((18, 168, 62, 184), "ad87cffa46d335cbd25dad79e223ac8eb3ef8962b15d015f4ba29001a5251ce6"),  # Pause
    ((18, 185, 62, 202), "db3731f1a36d6c8b96cbda9a32f772ec96df8cca08293173486fcdb2fe2b6606"),  # Scent
)
MENU_COLORS = {
    b"AAA": b"\x20\x30\x3c",
    b"\x00\xaa\xeb": b"\xe9\xf1\xee",
}
BUTTON_COLORS = {
    b"\x00\x00\x00": b"\x16\x22\x29",
    b"AAA": b"\x43\x54\x5a",
    b"\x82\x82\x82": b"\x83\x92\x91",
    b"\xc3\xc3\xc3": b"\xd6\xde\xd7",
    b"\xff\xff\xff": b"\xf3\xf3\xe9",
    b"\x00\x00\xd7": b"\x1d\x42\x60",
    b"\x00\x65\x10": b"\x16\x5a\x44",
}


def matching_ui(channels, width):
    """Yield the original RGB bytes for the exact control rectangles we can skin."""
    for bounds, fingerprint in REGIONS:
        left, top, right, bottom = bounds
        stride = right - left
        rgb = bytearray(stride * (bottom - top) * 3)
        for channel, values in enumerate(channels):
            for y in range(top, bottom):
                dest = (y - top) * stride * 3 + channel
                rgb[dest:dest + stride * 3:3] = values[y * width + left:y * width + right]
        if sha256(rgb).hexdigest() == fingerprint:
            yield bounds, bytes(rgb)
        elif bounds == MENU_BAR:
            # A menu highlight or another top bar means the resting UI is not visible.
            return


@cache
def _styled_rows(bounds, source):
    # Only fingerprint-verified bytes reach this cache.
    left, _, right, _ = bounds
    row_bytes = (right - left) * 3
    palette = MENU_COLORS if bounds == MENU_BAR else BUTTON_COLORS
    rows = []
    for start in range(0, len(source), row_bytes):
        colors = (source[i:i + 3] for i in range(start, start + row_bytes, 3))
        rows.append(b"".join(palette.get(color, color) * 2 for color in colors))
    return tuple(rows)


def paint_ui(pixels, channels, width):
    """Apply verified skins to the 2× RGB output without moving native hit targets."""
    row_bytes = width * 6
    for bounds, source in matching_ui(channels, width):
        left, top, _, _ = bounds
        for y, row in enumerate(_styled_rows(bounds, source), top):
            offset = y * 2 * row_bytes + left * 6
            pixels[offset:offset + len(row)] = row
            pixels[offset + row_bytes:offset + row_bytes + len(row)] = row
