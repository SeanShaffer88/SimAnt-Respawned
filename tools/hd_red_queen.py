"""Repaint verified Red castes within their exact native footprints."""

from hashlib import sha256
import re

from hd_actors import EDIT_BOTTOM, EDIT_LEFT, EDIT_RIGHT, EDIT_TOP, NEIGHBORS, _inside_edit, _paint_support
from hd_cursor import matched_cursor_raster
from hd_surface_scene import native_rgb_digest, quick_game_title_matches


_BLACK = b"\0\0\0"
_RED = b"\x04\x08\xdf"
_PERIMETER = {b"\x04\x2c\x55", b"\x38\x71\x92", b"\x41\x41\x41", b"\x82\x82\x82"}
_WORKER_PERIMETER = _PERIMETER | {b"\x10\x65\x00"}
_QUEEN_POSE = (23, 23, 119, 42, "77530e3e0955b29cbe4b16a525833864b21ff83bd07927a5bbcccf32beb7ca7c")
_WORKER_POSES = {
    (13, 16, 79, 20, "a149de4c02a95708a58ce8b997ff713687d447f64fcf7f2316568d84b96e8650"),
    (15, 15, 61, 13, "68c048cc8fe6e38616fb18148a20980dd56d0ff4963367be48a37a643cce060f"),
}
_SOLDIER_POSE = (16, 13, 89, 20, "70bcd2e9f53e5b2bbaad0d605744ca228211c06adb268596b6a6fd5984576c36")
_SOLDIER_PERIMETER = "5fc81de54a4ff7d3e66b6599eab02cb02b4de40dbf9b3a298af741501e797eaf"
# Three native orange perimeter pixels followed by two red shell pixels.
# The fourth byte of each XRGB pixel has no effect on the match.
_SOLDIER_SEED = re.compile(rb"\x00\x65\xff.\x00\x65\xff.\x00\x65\xff.\x04\x08\xdf.\x04\x08\xdf", re.DOTALL)
_RUNNING_PAUSE_CROP = (18, 169, 39, 182)
_RUNNING_PAUSE_DIGEST = "79c38ff8c56fff0c4678632e243c1f2bb48fa44775e1311015f8a865ca7362bb"


def _red_components(frame, sizes, bounds=(EDIT_LEFT, EDIT_TOP, EDIT_RIGHT, EDIT_BOTTOM)):
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (640, 480, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return
    left, top, right, bottom = bounds
    remaining = {}
    for y in range(top, bottom):
        row = raw[y * pitch + left * 4:y * pitch + right * 4]
        for color in (_BLACK, _RED):
            start = 0
            while (offset := row.find(color, start)) != -1:
                if offset % 4 == 0:
                    remaining[left + offset // 4, y] = color == _RED
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


def _pose_digest(component, left, top, width, height):
    points = sorted(component, key=lambda point: (point[1], point[0]))
    footprint = bytes(value for x, y in points for value in (x - left, y - top, component[x, y]))
    return sha256(bytes((width, height)) + footprint).hexdigest()


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
        pose = (*shape, _pose_digest(component, left, top, width, height))
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


def _soldier_perimeter_matches(raw, pitch, component, left, top):
    perimeter = {(x + dx, y + dy) for x, y in component for dx, dy in NEIGHBORS} - component.keys()
    pixels = bytearray()
    for x, y in sorted(perimeter, key=lambda point: (point[1], point[0])):
        offset = y * pitch + x * 4
        pixels.extend((x - left + 1, y - top + 1, *raw[offset:offset + 3]))
    return sha256(pixels).hexdigest() == _SOLDIER_PERIMETER


def paint_red_soldier(pixels, frame):
    """Shade the native Soldier shell in an accepted, running Quick Game Surface."""
    _, _, pitch, _, raw = frame
    if not quick_game_title_matches(raw, pitch):
        return
    if native_rgb_digest(raw, pitch, _RUNNING_PAUSE_CROP) != _RUNNING_PAUSE_DIGEST:
        return
    width, height, size, shell_size, expected = _SOLDIER_POSE
    cursor = None
    for seed in _SOLDIER_SEED.finditer(raw, EDIT_TOP * pitch, EDIT_BOTTOM * pitch):
        row, column = divmod(seed.start(), pitch)
        # This color sequence starts at native pose offset (1, 6).
        left, top = column // 4 - 1, row - 6
        if column % 4 or not _inside_edit(left - 1, top - 1, width + 2, height + 2):
            continue
        bounds = left - 1, top - 1, left + width + 1, top + height + 1
        for component in _red_components(frame, (size,), bounds):
            if sum(component.values()) != shell_size or not all(
                left <= x < left + width and top <= y < top + height for x, y in component
            ):
                continue
            if _pose_digest(component, left, top, width, height) != expected:
                continue
            if not _soldier_perimeter_matches(raw, pitch, component, left, top):
                continue
            if cursor is None:
                cursor = matched_cursor_raster(frame)
            if cursor and all(
                not (2 * bounds[1] <= row < 2 * bounds[3]
                     and start < 6 * bounds[2] and start + len(rgb) > 6 * bounds[0])
                for row, start, rgb in cursor
            ):
                shell = (point for point, red in component.items() if red)
                _paint_support(pixels, frame[0] * 6, shell, b"\x80\x28\x31", b"\xef\x85\x56", 0)
