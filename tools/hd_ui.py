"""Repaint verified DOS controls inside their original bounds."""

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

# The active top bar has a stable signature above the cursor in the captured
# dropdowns. Each entry records the panel and active title's half-open bounds.
DROPDOWNS = {
    "f2b169978f42d2b2d411ce63d6a70df96bed8708186151c70e7de5be9b983a61": ((5, 21, 75, 137), (0, 40)),
    "a9acd758ebbf1499aac917a92a778a1c7ec1f74805ef97d8f415491b5a7ca698": ((61, 21, 139, 123), (64, 120)),
    "366611ab510beb3df249a6fe5bcb3d6fdf1defbb8cbf02f18e514de2d796ceb3": ((125, 21, 219, 137), (144, 184)),
    "466a2459eab5b79092d4fe233213099ff5a5ae8ef91889d0ec8b6475b2b50067": ((189, 21, 307, 109), (208, 272)),
    "f4e478471af1c543a404987c8493da70bea50508c10b66ae3680d6c32e9709f3": ((293, 21, 355, 109), (296, 344)),
}
CYAN = b"\x00\xaa\xeb"
GRAY = b"AAA"
SELECTED_COLORS = {CYAN: b"\x23\x59\x6b", GRAY: b"\xff\xf8\xe5"}
BORDER_COLORS = {CYAN: b"\x69\xaf\xbe"}
DROPDOWN_COLORS = {GRAY, CYAN, b"\xff\xff\xff", b"\xff\xf3\x04", b"\x00\x00\x00", b"\xff\x65\x00"}
CURSOR_SHADOW = ((2, 3), (4, 3), (2, 4), (3, 4), (5, 4), (2, 5),
                 (4, 5), (6, 5), (2, 6), (5, 6), (7, 6))
SCENT_BOUNDS = (64, 188, 149, 296)
SCENT_BORDER_SHA256 = "e0c605c00fa68ba71ae7d80641b8d15fed72e988cc9af4983a419ab860df56dd"
SCENT_HIGHLIGHT = b"\xdf\x08\x04"
SCENT_BACKGROUND = b"\xc3\xc3\xc3"
SCENT_ROW_STARTS = range(192, 293, 17)
SCENT_SELECTED_COLORS = {
    SCENT_HIGHLIGHT: SELECTED_COLORS[CYAN],
    SCENT_BACKGROUND: SELECTED_COLORS[GRAY],
    b"\x45\x00\xa6": SELECTED_COLORS[GRAY],
    b"\x00\x65\x10": SELECTED_COLORS[GRAY],
}
SCENT_LABEL_COLORS = {
    SCENT_BACKGROUND: BUTTON_COLORS[SCENT_BACKGROUND],
    SCENT_HIGHLIGHT: b"\xa5\x26\x25",
}


def _rgb_row(raw, pitch, y, left, right):
    data = raw[y * pitch + left * 4:y * pitch + right * 4]
    rgb = bytearray((right - left) * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = data[2::4], data[1::4], data[0::4]
    return bytes(rgb)


def matching_scent_menu(frame):
    """Return the native Scent label rows and their selected index."""
    width, height, pitch, pixel_format, raw = frame
    if (width, height, pixel_format) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return None
    left, top, right, bottom = SCENT_BOUNDS
    corner = top * pitch + left * 4
    if raw[corner:corner + 3] != SCENT_BACKGROUND:
        return None

    border = bytearray()
    for y in range(top, bottom):
        if y < 191:
            border.extend(_rgb_row(raw, pitch, y, left, right))
        elif y >= 294:
            # The cursor can cross the middle of the bottom edge on R-Trail.
            border.extend(_rgb_row(raw, pitch, y, left, 96))
            border.extend(_rgb_row(raw, pitch, y, 124, right))
        else:
            border.extend(_rgb_row(raw, pitch, y, left, 67))
            border.extend(_rgb_row(raw, pitch, y, 146, right))
    if sha256(border).hexdigest() != SCENT_BORDER_SHA256:
        return None

    selected = None
    labels = []
    for index, y in enumerate(SCENT_ROW_STARTS):
        edge = _rgb_row(raw, pitch, y, 67, 68)
        expected = SCENT_BACKGROUND
        if edge == b"\xff\xff\xff" and selected is None:
            selected = index
            expected = SCENT_HIGHLIGHT
        elif edge != b"\x00\x00\x00":
            return None
        for sample in (y, y + 15):
            fill = _rgb_row(raw, pitch, sample, 101, 145)
            if sum(fill[x:x + 3] == expected for x in range(0, len(fill), 3)) < 31:
                return None
        # Off has no icon. For the other rows, keep the entire icon column.
        label_left = 68 if index == 0 else 101
        rows = tuple(_rgb_row(raw, pitch, row, label_left, 145) for row in range(y, y + 16))
        labels.append((label_left, y, rows))
    return (labels, selected) if selected is not None else None


def paint_scent_menu(pixels, width, menu):
    """Restyle only verified native Scent labels in the doubled raster."""
    labels, selected = menu
    stride = width * 6
    for index, (left, top, rows) in enumerate(labels):
        palette = SCENT_SELECTED_COLORS if index == selected else SCENT_LABEL_COLORS
        for y, row in enumerate(rows, top):
            colors = (row[x:x + 3] for x in range(0, len(row), 3))
            styled = b"".join(palette.get(color, color) * 2 for color in colors)
            offset = y * 2 * stride + left * 6
            pixels[offset:offset + len(styled)] = styled
            pixels[offset + stride:offset + stride + len(styled)] = styled


def _cursor_shadow(raw, pitch, width, bottom):
    # The native cursor's first two rows identify gray shadow pixels that
    # otherwise look exactly like text or background from the menu palette.
    white = b"\xff\xff\xff"
    tip = white + b"\xff\x65\x00" + b"\xff\xf3\x04" * 6 + white
    start = 0
    while (index := raw.find(b"\x00\x65\xff", start, bottom * pitch)) >= 0:
        start = index + 1
        y, offset = divmod(index, pitch)
        x = offset // 4 - 1
        if (offset % 4 == 0 and y > 0 and 0 <= x <= width - 9
                and _rgb_row(raw, pitch, y - 1, x, x + 9) == white * 9
                and _rgb_row(raw, pitch, y, x, x + 9) == tip):
            return {(x + dx, y - 1 + dy) for dx, dy in CURSOR_SHADOW}
    return set()


def matching_dropdown(frame):
    """Return the verified native menu bounds and RGB rows to restyle."""
    width, height, pitch, pixel_format, raw = frame
    if (width, height, pixel_format) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return None
    if not any(raw[pitch + left * 4:pitch + left * 4 + 3] == CYAN[::-1]
               for _, (left, _) in DROPDOWNS.values()):
        return None

    header = tuple(_rgb_row(raw, pitch, y, 0, width) for y in range(16))
    menu = DROPDOWNS.get(sha256(b"".join(header[:14])).hexdigest())
    if menu is None:
        return None

    bounds, title = menu
    left, top, right, bottom = bounds
    panel = tuple(_rgb_row(raw, pitch, y, left, right) for y in range(top, bottom))
    rail = CYAN * 2
    if any(not row.startswith(rail) or not row.endswith(rail) for row in panel):
        return None
    if panel[-2:] != (CYAN * (right - left),) * 2:
        return None
    if any(row[x:x + 3] not in DROPDOWN_COLORS for row in panel for x in range(0, len(row), 3)):
        return None

    # Each highlighted row starts with a pair of cyan fill lines. A cursor
    # over the fill can remove a few pixels without changing the selected row.
    fill_width = right - left - 6
    selected = next((y for y in range(1, len(panel) - 2, 14)
                     if all(row[9:-9].count(CYAN) * 3 >= fill_width * 2
                            for row in panel[y:y + 2])), None)
    return bounds, title, header, panel, selected, _cursor_shadow(raw, pitch, width, bottom)


def paint_dropdown(pixels, width, menu):
    """Restyle only the matched dropdown and its menu bar on a 2× frame."""
    bounds, (title_left, title_right), header, panel, selected, cursor_shadow = menu
    left, top, right, _ = bounds
    row_bytes = width * 6

    def paint_row(x, y, row, palette):
        styled = bytearray()
        for start in range(0, len(row), 3):
            color = row[start:start + 3]
            pixel = color if (x + start // 3, y) in cursor_shadow else palette.get(color, color)
            styled += pixel * 2
        offset = y * row_bytes * 2 + x * 6
        pixels[offset:offset + len(styled)] = styled
        pixels[offset + row_bytes:offset + row_bytes + len(styled)] = styled

    for y, row in enumerate(header):
        if 1 <= y < 15:
            paint_row(0, y, row[:title_left * 3], MENU_COLORS)
            paint_row(title_left, y, row[title_left * 3:title_right * 3], SELECTED_COLORS)
            paint_row(title_right, y, row[title_right * 3:], MENU_COLORS)
        else:
            paint_row(0, y, row, MENU_COLORS)

    for y, row in enumerate(panel):
        screen_y = top + y
        if y >= len(panel) - 2:
            paint_row(left, screen_y, row, BORDER_COLORS)
            continue
        paint_row(left, screen_y, row[:6], BORDER_COLORS)
        if selected is not None and selected <= y < selected + 14:
            paint_row(left + 2, screen_y, row[6:9], MENU_COLORS)
            paint_row(left + 3, screen_y, row[9:-9], SELECTED_COLORS)
            paint_row(right - 3, screen_y, row[-9:-6], MENU_COLORS)
        else:
            paint_row(left + 2, screen_y, row[6:-6], MENU_COLORS)
        paint_row(right - 2, screen_y, row[-6:], BORDER_COLORS)


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
