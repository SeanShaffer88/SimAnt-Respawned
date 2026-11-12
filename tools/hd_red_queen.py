"""Repaint verified Red Nest castes within their exact native footprints."""

from hashlib import sha256

from hd_actors import EDIT_BOTTOM, EDIT_LEFT, EDIT_RIGHT, EDIT_TOP, NEIGHBORS, _inside_edit, _paint_support
from hd_cursor import matched_cursor_raster


_BLACK = b"\0\0\0"
_RED = b"\x04\x08\xdf"
_PERIMETER = {b"\x04\x2c\x55", b"\x38\x71\x92", b"\x41\x41\x41", b"\x82\x82\x82"}
_WORKER_PERIMETER = _PERIMETER | {b"\x10\x65\x00"}
_QUEEN_POSE = (23, 23, 119, 42, "77530e3e0955b29cbe4b16a525833864b21ff83bd07927a5bbcccf32beb7ca7c")
_WORKER_POSES = {
    (13, 16, 79, 20, "a149de4c02a95708a58ce8b997ff713687d447f64fcf7f2316568d84b96e8650"),
    (15, 15, 61, 13, "68c048cc8fe6e38616fb18148a20980dd56d0ff4963367be48a37a643cce060f"),
}


def _red_components(frame, sizes):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return
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
            return

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
        if len(component) in sizes:
            yield component


def _clear_perimeter(frame, component, palette):
    _, _, pitch, _, raw = frame
    for x, y in component:
        for dx, dy in NEIGHBORS:
            neighbor = x + dx, y + dy
            if neighbor not in component:
                offset = neighbor[1] * pitch + 4 * neighbor[0]
                if raw[offset:offset + 3] not in palette:
                    return False
    return True


def _red_supports(frame, include_workers):
    poses = {_QUEEN_POSE, *_WORKER_POSES} if include_workers else {_QUEEN_POSE}
    dimensions = {pose[:4] for pose in poses}
    sizes = {pose[2] for pose in poses}
    queen = None
    queen_ambiguous = False
    workers = []
    cursor = None
    for component in _red_components(frame, sizes):
        left, top = min(x for x, _ in component), min(y for _, y in component)
        right, bottom = max(x for x, _ in component), max(y for _, y in component)
        width, height = right - left + 1, bottom - top + 1
        shape = width, height, len(component), sum(component.values())
        if shape not in dimensions:
            continue
        points = sorted(component, key=lambda point: (point[1], point[0]))
        footprint = bytes(value for x, y in points for value in (x - left, y - top, component[x, y]))
        pose = (*shape, sha256(bytes((width, height)) + footprint).hexdigest())
        has_margin = _inside_edit(left - 1, top - 1, width + 2, height + 2)
        if pose == _QUEEN_POSE:
            if queen is not None or not has_margin:
                queen_ambiguous = True
            queen = component
        elif pose in _WORKER_POSES and include_workers and has_margin:
            if not _clear_perimeter(frame, component, _WORKER_PERIMETER):
                continue
            if cursor is None:
                cursor = matched_cursor_raster(frame)
            if cursor and all(
                not (2 * (top - 1) <= row < 2 * (bottom + 2)
                     and start < 6 * (right + 2) and start + len(rgb) > 6 * (left - 1))
                for row, start, rgb in cursor
            ):
                workers.extend(point for point, red in component.items() if red)
    queen_support = ()
    if queen is not None and not queen_ambiguous and _clear_perimeter(frame, queen, _PERIMETER):
        queen_support = tuple(point for point, red in queen.items() if red)
    return queen_support, tuple(workers)


def red_queen_support(frame):
    """Return native red-shell coordinates for one complete, isolated Queen."""
    return _red_supports(frame, include_workers=False)[0]


def paint_red_queen(pixels, frame):
    """Shade only the Queen's authenticated red shell pixels at 2×."""
    _paint_support(pixels, frame[0] * 6, red_queen_support(frame), b"\x99\x22\x2c", b"\xf2\x75\x4f", 0)


def paint_red_castes(pixels, frame):
    """Shade the authenticated Queen and Worker shell pixels at 2×."""
    queen, workers = _red_supports(frame, include_workers=True)
    stride = frame[0] * 6
    _paint_support(pixels, stride, queen, b"\x99\x22\x2c", b"\xf2\x75\x4f", 0)
    _paint_support(pixels, stride, workers, b"\x89\x26\x30", b"\xe0\x5b\x4d", 0)
