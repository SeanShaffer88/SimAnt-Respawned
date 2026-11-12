"""Restyle observed DOS ant poses within their native footprints."""

from collections import deque
from hashlib import sha256
from struct import unpack_from

from verify_synchronized_scene import NEST, SCALAR_START


PLAYER_HEADING = SCALAR_START + 0x51616 - 0x515FC
PLAYER_WINDOW = (19, 17)
PLAYER_CENTER = (9, 8)
GOLD_BGR = b"\x04\xf3\xff"
BLACK_BGR = b"\x00\x00\x00"
EDIT_LEFT, EDIT_TOP, EDIT_RIGHT, EDIT_BOTTOM = 64, 42, 416, 377

# Hashes authenticate the positive palette footprint in the full projected
# window. In particular, a cursor over the ant must not count as a new pose.
PLAYER_POSES = {
    2: "0a8b1c2dd0df47114654ef70a302d4e91e17130b9eee520fc22299260d4410d4",
    3: "b8cc72dc7c24de737333fe5582759200a386ed2b66b9279c84aebddb0a20737e",
    7: "8f93af79eebaded823ae4c002a416b56ea0708f81b6a1d8c9ed0236bad3403e7",
}
# The original DOS manual identifies the large black ant in the opening nest
# as the queen. Require its complete observed silhouette, not size or color
# alone. Unsupported poses, overlaps, and other castes keep their native art.
QUEEN_POSE = "c16f940ba876f7ac6711d31ec257e60d1ecc3bdc34584a8dbbbdf38d26489255"
QUEEN_SIZE = 79
NEIGHBORS = ((-1, -1), (0, -1), (1, -1), (-1, 0),
             (1, 0), (-1, 1), (0, 1), (1, 1))


def _inside_edit(x, y, width, height):
    return (EDIT_LEFT <= x and EDIT_TOP <= y
            and x + width <= EDIT_RIGHT and y + height <= EDIT_BOTTOM
            and (y + height <= 362 or x + width <= 400))


def _paint_support(pixels, stride, points, base, highlight, phase):
    for x, y in points:
        for dy in range(2):
            for dx in range(2):
                # Subpixel light gives the body a readable edge. The diagonal
                # accent alternates with the original ant's world tile.
                lit = (dx == dy and (x + y + phase) % 2 == 0) or (dx == 0 and dy == 0)
                offset = (2 * y + dy) * stride + (2 * x + dx) * 3
                pixels[offset:offset + 3] = highlight if lit else base


def _player_support(frame, payload, observation):
    center = observation.get("visible_ant")
    if center is None:
        return (), 0
    heading = unpack_from("<H", payload, PLAYER_HEADING)[0]
    signature = PLAYER_POSES.get(heading)
    if signature is None:
        return (), 0

    _, _, pitch, _, raw = frame
    width, height = PLAYER_WINDOW
    left, top = (center[0] - PLAYER_CENTER[0], center[1] - PLAYER_CENTER[1])
    if not _inside_edit(left, top, width, height):
        return (), 0
    points, mask = [], 0
    for y in range(height):
        for x in range(width):
            start = (top + y) * pitch + (left + x) * 4
            if raw[start:start + 3] == GOLD_BGR:
                points.append((left + x, top + y))
                mask |= 1 << (y * width + x)
    if sha256(mask.to_bytes((width * height + 7) // 8, "little")).hexdigest() != signature:
        return (), 0
    world_x, world_y, _ = observation["ant"]
    step = world_y if heading in (0, 4) else world_x
    return points, step % 2


def _queen_support(frame):
    _, _, pitch, _, raw = frame
    black = set()
    for y in range(EDIT_TOP, EDIT_BOTTOM):
        begin = y * pitch + EDIT_LEFT * 4
        row = raw[begin:y * pitch + EDIT_RIGHT * 4]
        blue = row[::4]
        x = blue.find(b"\x00")
        while x != -1:
            if row[x * 4:x * 4 + 3] == BLACK_BGR:
                black.add((EDIT_LEFT + x, y))
            x = blue.find(b"\x00", x + 1)
        if len(black) > 4096:
            return ()

    match = ()
    while black:
        component = []
        pending = deque([black.pop()])
        while pending:
            x, y = pending.popleft()
            component.append((x, y))
            for dx, dy in NEIGHBORS:
                neighbor = (x + dx, y + dy)
                if neighbor in black:
                    black.remove(neighbor)
                    pending.append(neighbor)
        if len(component) != QUEEN_SIZE:
            continue
        left, top = min(x for x, _ in component), min(y for _, y in component)
        width = max(x for x, _ in component) - left + 1
        height = max(y for _, y in component) - top + 1
        if (width, height) != (23, 22) or not _inside_edit(left, top, width, height):
            continue
        points = sorted(component, key=lambda point: (point[1], point[0]))
        footprint = bytes(value for x, y in points for value in (x - left, y - top))
        if sha256(bytes((width, height)) + footprint).hexdigest() == QUEEN_POSE:
            if match:
                return ()
            match = points
    return match


def paint_actors(pixels, frame, payload, observation):
    """Write only the RGB subpixels supported by an authenticated ant pose."""
    if observation.get("result") != "accepted":
        return
    stride = frame[0] * 6
    if observation.get("edit") == NEST:
        _paint_support(pixels, stride, _queen_support(frame),
                       b"\x27\x1e\x28", b"\x64\x48\x58", 0)
    points, phase = _player_support(frame, payload, observation)
    _paint_support(pixels, stride, points, b"\xd9\x8f\x22", b"\xff\xec\x81", phase)
