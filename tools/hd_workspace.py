"""Restyle the visible DOS desktop behind the original window arrangement."""

from hd_cursor import matched_cursor_raster


WORKSPACE_RGB = bytes((48, 71, 81))
_WIDTH, _HEIGHT = 640, 480
_NATIVE_CYAN = tuple(bytes((value,)) * _WIDTH for value in (235, 170, 0))
_NATIVE_RAILS = (b"\x04\xf3\xff", b"\x41\x41\x41")
_BACKDROP_ROW = WORKSPACE_RGB * (2 * _WIDTH)
_BANDS = (
    (0, 17, ()),
    (17, 22, ((0, 640),)),
    (22, 62, ((0, 14), (418, 640))),
    (62, 379, ((0, 14), (578, 640))),
    (379, 386, ((0, 62), (578, 640))),
    (386, 478, ((0, 86), (300, 342), (556, 640))),
    (478, 479, ((0, 342), (556, 640))),
    (479, 480, ((0, 640),)),
)
_EXTERIOR = tuple(runs for top, bottom, runs in _BANDS for _ in range(top, bottom))


def _inward_rails():
    """Find the non-desktop pixels that touch the exterior orthogonally."""
    masks = [sum(((1 << (right-left)) - 1) << left for left, right in runs) for runs in _EXTERIOR]
    width_mask = (1 << _WIDTH) - 1
    rows = []
    for y in range(22, 479):
        here = masks[y]
        neighbors = masks[y-1] | masks[y+1] | (here >> 1) | (here << 1)
        witnesses = neighbors & ~here & width_mask
        columns = []
        while witnesses:
            bit = witnesses & -witnesses
            columns.append(bit.bit_length() - 1)
            witnesses ^= bit
        if columns:
            rows.append((y, tuple(columns)))
    return tuple(rows)


_RAILS = _inward_rails()


def verified_workspace_runs(frame):
    """Return native (row, left, right) runs only after all layout witnesses match."""
    width, height, pitch, fmt, raw = frame
    if (width, height, fmt) != (_WIDTH, _HEIGHT, 1) or pitch < width * 4 or len(raw) < pitch * height:
        return ()
    # The native arrow is opaque only within its exact matched row runs.
    cursor = {row//2: (left//6, (left+len(rgb))//6)
              for row, left, rgb in matched_cursor_raster(frame) if row % 2 == 0}
    result = []
    for y, runs in enumerate(_EXTERIOR):
        occupied = cursor.get(y)
        for left, right in runs:
            spans = ((left, right),) if occupied is None else (
                (left, min(right, occupied[0])), (max(left, occupied[1]), right),
            )
            for start, stop in spans:
                if start >= stop:
                    continue
                native = raw[y*pitch+start*4:y*pitch+stop*4]
                if any(native[channel::4] != expected[:stop-start]
                       for channel, expected in enumerate(_NATIVE_CYAN)):
                    return ()
                result.append((y, start, stop))
    for y, columns in _RAILS:
        left, right = cursor.get(y, (0, 0))
        for x in columns:
            if left <= x < right:
                continue
            start = y * pitch + x * 4
            if raw[start:start+3] not in _NATIVE_RAILS:
                return ()
    return tuple(result)


def paint_workspace(pixels, frame):
    """Paint the verified desktop pixels at 2×, preserving all window and cursor pixels."""
    row_bytes = frame[0] * 6
    for y, left, right in verified_workspace_runs(frame):
        run = _BACKDROP_ROW[:(right-left)*6]
        offset = 2 * y * row_bytes + left * 6
        pixels[offset:offset+len(run)] = run
        pixels[offset+row_bytes:offset+row_bytes+len(run)] = run
