"""Repaint the native-labeled Red Queen's shell within its exact footprint."""

from hashlib import sha256

from hd_actors import EDIT_BOTTOM, EDIT_LEFT, EDIT_RIGHT, EDIT_TOP, NEIGHBORS, _inside_edit, _paint_support


_BLACK = b"\0\0\0"
_RED = b"\x04\x08\xdf"
_PERIMETER = {b"\x04\x2c\x55", b"\x38\x71\x92", b"\x41\x41\x41", b"\x82\x82\x82"}
_SIGNATURE = "77530e3e0955b29cbe4b16a525833864b21ff83bd07927a5bbcccf32beb7ca7c"


def red_queen_support(frame):
    """Return native red-shell coordinates for one complete, isolated Queen."""
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return ()
    remaining = {}
    for y in range(EDIT_TOP, EDIT_BOTTOM):
        row = raw[y * pitch + EDIT_LEFT * 4:y * pitch + EDIT_RIGHT * 4]
        for color in (_BLACK, _RED):
            start = 0
            while (offset := row.find(color, start)) != -1:
                if offset % 4 == 0:
                    remaining[EDIT_LEFT + offset // 4, y] = color == _RED
                start = offset + 1
        if len(remaining) > 4096:
            return ()

    queen = None
    while remaining:
        origin, role = remaining.popitem()
        component = {origin: role}
        pending = [origin]
        for x, y in pending:
            for dx, dy in NEIGHBORS:
                neighbor = x + dx, y + dy
                role = remaining.pop(neighbor, None)
                if role is not None:
                    component[neighbor] = role
                    pending.append(neighbor)
        if len(component) != 119:
            continue
        left, top = min(x for x, _ in component), min(y for _, y in component)
        right, bottom = max(x for x, _ in component), max(y for _, y in component)
        if (right - left, bottom - top) != (22, 22) or sum(component.values()) != 42:
            continue
        points = sorted(component, key=lambda point: (point[1], point[0]))
        footprint = bytes(value for x, y in points for value in (x - left, y - top, component[x, y]))
        if sha256(bytes((23, 23)) + footprint).hexdigest() != _SIGNATURE:
            continue
        if queen is not None or not _inside_edit(left - 1, top - 1, 25, 25):
            return ()
        queen = component

    if queen is None:
        return ()
    for x, y in queen:
        for dx, dy in NEIGHBORS:
            neighbor = x + dx, y + dy
            if neighbor not in queen:
                offset = neighbor[1] * pitch + 4 * neighbor[0]
                if raw[offset:offset + 3] not in _PERIMETER:
                    return ()
    return tuple(point for point, red in queen.items() if red)


def paint_red_queen(pixels, frame):
    """Shade only the Queen's authenticated red shell pixels at 2×."""
    _paint_support(pixels, frame[0] * 6, red_queen_support(frame), b"\x99\x22\x2c", b"\xf2\x75\x4f", 0)
