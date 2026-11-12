"""Presentation-only raster for the verified DOS Surface and underground views."""

from functools import cache
from random import Random

from hd_actors import nest_supports, paint_actors, paint_nest_supports
from hd_anthill_rim import paint_anthill_rim
from hd_cursor import paint_cursor
from hd_foliage import paint_foliage
from hd_food import paint_food
from hd_full_nest_scene import (
    FULL_BLACK_NEST_LAYOUT, NEST_GRID_X, NEST_GRID_Y, NEST_PAINT_BOTTOM, NEST_PAINT_TOP, NEST_TERRAIN_BYTES,
    full_black_nest_camera, full_black_nest_raster,
)
from hd_nest_roots import paint_nest_roots
from hd_pebbles import paint_boulders, paint_pebbles
from hd_red_nest_scene import BOTTOM as RED_RASTER_BOTTOM, OCCUPIED_RED_CAMERA, OCCUPIED_RED_LAYOUT
from hd_red_nest_scene import TOP as RED_RASTER_TOP, occupied_red_raster
from hd_red_queen import paint_red_castes, paint_red_queen
from hd_surface_scene import (
    EAST_SURFACE_LAYOUT, FULL_LOADED_SURFACE_CAMERA, FULL_LOADED_SURFACE_LAYOUT, FULL_PANNED_SURFACE_LAYOUT,
    FULL_SURFACE_CAMERAS, FULL_SURFACE_LAYOUT,
    east_surface_camera, full_surface_camera,
)
from hd_trails import paint_trails
from hd_tutorial_scene import TUTORIAL_BOUNDS, TUTORIAL_CAMERA, TUTORIAL_NEST_LAYOUT, tutorial_nest_raster
from hd_ui import (
    MENU_BAR, matching_dropdown, matching_scent_menu, matching_ui,
    paint_dropdown, paint_scent_menu, paint_ui,
)
from hd_workspace import paint_workspace
from hd_yard_scene import verified_house_runs, verified_yard_runs
from verify_synchronized_scene import CAPACITY, NEST, RED_NEST, SURFACE, TERRAIN_START


# The fixture's Edit pane and terrain grid use different left edges.
LEFT, TOP, RIGHT, BOTTOM = 64, 42, 416, 377
TILE_LEFT = 62
MAP_BYTES = 8192
TEXTURE_SIZE = 256
TEXTURE_REPEATS = 1 + (2 * (RIGHT - LEFT) + TEXTURE_SIZE - 1) // TEXTURE_SIZE
WHITE_TILE = b"\xff" * 16
BLACK_TILE = b"\x00" * 16
SURFACE_GROUND = ((85, 44, 4), (146, 113, 56))
SURFACE_EVEN_COLUMNS = int.from_bytes(b"\xff\x00" * ((RIGHT - LEFT) // 2), "little")
SURFACE_STONE = ((65, 65, 65), (130, 130, 130), (195, 195, 195))
NEST_EARTH = ((85, 44, 4),)
NEST_TUNNEL = ((146, 113, 56),)
OVERLAY_RUNS = tuple(bytes([tone]) * 40 for tone in (130, 195))
NO_RESIZE_GRIP = (1 << (8 * (400 - LEFT))) - 1


def _ppm(width, height, pixels):
    return f"P6\n{width} {height}\n255\n".encode("ascii") + pixels


def _rgb_channels(frame):
    width, height, pitch, pixel_format, raw = frame
    if pixel_format != 1 or width <= 0 or height <= 0 or pitch < width * 4:
        raise ValueError("Expected a valid XRGB8888 software frame")
    if len(raw) < pitch * height:
        raise ValueError("Truncated software frame")
    if pitch != width * 4:
        raw = b"".join(raw[y * pitch:y * pitch + width * 4] for y in range(height))
    return raw[2::4], raw[1::4], raw[0::4]


def render_classic(frame):
    """Encode the original XRGB frame as a native-size P6 image."""
    width, height = frame[:2]
    pixels = bytearray(width * height * 3)
    for channel, values in enumerate(_rgb_channels(frame)):
        pixels[channel::3] = values
    return _ppm(width, height, pixels)


def _doubled_rgb(width, height, channels):
    stride = width * 6
    pixels = bytearray(stride * height * 2)
    for y in range(height):
        start = y * width
        row = bytearray(stride)
        for channel, values in enumerate(channels):
            row[channel::3] = _double(values[start:start + width])
        offset = y * stride * 2
        pixels[offset:offset + stride * 2] = row + row
    return pixels


def render_dropdown_only(frame):
    """Restyle a verified open menu over a 2× native frame."""
    menu = matching_dropdown(frame)
    if menu is not None:
        paint = paint_dropdown
    else:
        menu = matching_scent_menu(frame)
        if menu is None:
            return None
        paint = paint_scent_menu
    width, height = frame[:2]
    pixels = _doubled_rgb(width, height, _rgb_channels(frame))
    paint(pixels, width, menu)
    paint_cursor(pixels, frame)
    return _ppm(width * 2, height * 2, pixels)


def _render_overview(frame, runs):
    if runs is None:
        return None
    width, height = frame[:2]
    pixels = _doubled_rgb(width, height, _rgb_channels(frame))
    for row, left, colors in runs:
        start = row * width * 6 + left
        pixels[start:start + len(colors)] = colors
    paint_cursor(pixels, frame)
    return _ppm(width * 2, height * 2, pixels)


def render_full_yard(frame, scalars):
    """Repaint a verified original Yard while keeping the native UI and blink."""
    return _render_overview(frame, verified_yard_runs(frame, scalars))


def render_full_house(frame, scalars):
    """Repaint verified floor and siding in the native House cutaway."""
    return _render_overview(frame, verified_house_runs(frame, scalars))


def render_caste_only(frame):
    """Redraw verified Black Nest castes over a 2× native frame."""
    supports = [(caste, points) for caste, points in nest_supports(frame) if caste != "queen"]
    if not supports:
        return None
    width, height = frame[:2]
    channels = _rgb_channels(frame)
    menu = next(matching_ui(channels, width), None)
    if menu is None or menu[0] != MENU_BAR:
        return None
    pixels = _doubled_rgb(width, height, channels)
    paint_nest_supports(pixels, width * 6, supports)
    paint_cursor(pixels, frame)
    return _ppm(width * 2, height * 2, pixels)


@cache
def _match_table(value):
    table = bytearray(256)
    table[value] = 255
    return bytes(table)


def _palette_mask(channels, palette):
    """Compare exact RGB triples in bulk without interpreting unknown pixels."""
    result = 0
    for color in palette:
        red, green, blue = (
            int.from_bytes(values.translate(_match_table(tone)), "little")
            for values, tone in zip(channels, color)
        )
        result |= red & green & blue
    return result


def _surface_soil_row(channels, y):
    # LEFT is even. The DOS dither has a fixed phase in the framebuffer.
    dark = _palette_mask(channels, SURFACE_GROUND[:1])
    light = _palette_mask(channels, SURFACE_GROUND[1:])
    if y % 2:
        dark, light = light, dark
    return (dark & SURFACE_EVEN_COLUMNS) | (light & ~SURFACE_EVEN_COLUMNS)


def _surface_ground_mask(center, above, below, green):
    # One byte per column. Shifts cannot carry a neighbor from another row.
    left, right = center << 8, center >> 8
    horizontal = left & right
    vertical = above & below
    two_neighbors = horizontal | vertical | ((left | right) & (above | below))
    return (center & two_neighbors) | (green & horizontal & vertical)


def _double(values):
    wide = bytearray(len(values) * 2)
    wide[0::2] = values
    wide[1::2] = values
    return wide


def _texture_noise(random, cell):
    """Blend a wrapped noise grid without seams at the texture boundary."""
    count = TEXTURE_SIZE // cell
    grid = [[random.random() for _ in range(count)] for _ in range(count)]
    weights = [(i / cell) ** 2 * (3 - 2 * i / cell) for i in range(cell)]

    def row(y):
        index, offset = divmod(y, cell)
        top, bottom = grid[index], grid[(index + 1) % count]
        blend = weights[offset]
        across = [a + (b - a) * blend for a, b in zip(top, bottom)]
        return [
            start + (end - start) * weight
            for start, end in zip(across, across[1:] + across[:1])
            for weight in weights
        ]

    return row


@cache
def _texture(base, accent, seed, grass=False):
    """Build a quiet world-space material with sparse, shallow surface detail."""
    random = Random(seed)
    patches = _texture_noise(random, 64)
    grit = _texture_noise(random, 16)
    relief = [bytearray(TEXTURE_SIZE) for _ in range(TEXTURE_SIZE)]
    for _ in range(110):
        x, y = random.randrange(TEXTURE_SIZE), random.randrange(TEXTURE_SIZE)
        length = random.randrange(2, 7)
        for step in range(length):
            if grass:
                relief[(y - step) % TEXTURE_SIZE][(x + step // 2) % TEXTURE_SIZE] = 8
                relief[(y - step) % TEXTURE_SIZE][(x - step // 3) % TEXTURE_SIZE] = 5
            else:
                relief[y][(x + step) % TEXTURE_SIZE] = 6
                relief[(y + 1) % TEXTURE_SIZE][(x + step) % TEXTURE_SIZE] = 2

    rows = []
    for y in range(TEXTURE_SIZE):
        channels = [bytearray(), bytearray(), bytearray()]
        for x, (patch, grit_value) in enumerate(zip(patches(y), grit(y))):
            blend = patch * 0.74 + grit_value * 0.26
            grain = random.randrange(-3, 4)
            detail = relief[y][x]
            for channel, start, end in zip(channels, base, accent):
                channel.append(round(start + (end - start) * blend) + grain + detail)
        rows.append(tuple(bytes(channel) * TEXTURE_REPEATS for channel in channels))
    return tuple(rows)


def _tile_masks(first, second, stride, world_y, camera_x, view):
    broad, specific = [], []
    world_x = camera_x
    for _ in range((RIGHT - TILE_LEFT + 15) // 16):
        index = world_y * stride + world_x
        terrain = first[index] if world_x < 64 and world_y < 64 and first[index] == second[index] else 0
        if view == SURFACE:
            broad.append(WHITE_TILE if terrain in (11, 13) else BLACK_TILE)
            specific.append(WHITE_TILE if terrain == 13 else BLACK_TILE)
        else:
            broad.append(WHITE_TILE if terrain in (10, 12, 15) else BLACK_TILE)
            specific.append(WHITE_TILE if terrain in (12, 15) else BLACK_TILE)
        world_x += 1
    clip_start = LEFT - TILE_LEFT
    clip_end = RIGHT - TILE_LEFT
    return tuple(int.from_bytes(b"".join(mask)[clip_start:clip_end], "little")
                 for mask in (broad, specific))


def _wide_mask(mask, width=RIGHT - LEFT):
    return int.from_bytes(_double(mask.to_bytes(width, "little")), "little")


def _paint(values, paint, mask, start, left=LEFT, right=RIGHT):
    if not mask:
        return
    begin, end = left * 2, right * 2
    original = int.from_bytes(values[begin:end], "little")
    painted = paint[start:start + end - begin]
    if len(painted) < end - begin:
        painted += paint[:end - begin - len(painted)]
    texture = int.from_bytes(painted, "little")
    values[begin:end] = (original ^ ((original ^ texture) & mask)).to_bytes(end - begin, "little")


def _has_neutral_overlay(channels):
    # A contiguous neutral panel can share the native stone palette. Keep the
    # current Classic picture whenever that distinction is ambiguous.
    for y in range(TOP, BOTTOM):
        rows = [channel[y * 640 + LEFT:y * 640 + RIGHT] for channel in channels]
        for run in OVERLAY_RUNS:
            offset = rows[0].find(run)
            while offset != -1:
                if all(row.startswith(run, offset) for row in rows[1:]):
                    return True
                offset = rows[0].find(run, offset + 1)
    return False


def neutral_overlay_open(frame):
    """Check the RGB overlay guard without relying on the unused XRGB byte."""
    return _has_neutral_overlay(_rgb_channels(frame))


def _nest_textures():
    return (
        _texture((76, 51, 38), (98, 67, 47), 47),
        _texture((148, 105, 65), (174, 131, 83), 73),
    )


def _render_tutorial_terrain(frame, payload, observation):
    if observation["edit"] != NEST or tuple(observation["camera"]) != TUTORIAL_CAMERA:
        raise ValueError("Unsupported Tutorial camera")
    width, height = frame[:2]
    channels = _rgb_channels(frame)
    masks = tutorial_nest_raster(frame, payload, tuple(observation["ant"][:2]))
    if masks is None:
        raise ValueError("Unsupported Tutorial terrain")
    pixels = _doubled_rgb(width, height, channels)
    left, top, right, _ = TUTORIAL_BOUNDS
    span = right - left
    camera_x, camera_y = TUTORIAL_CAMERA
    texture_x = (camera_x * 32 + (left - NEST_GRID_X) * 2) % TEXTURE_SIZE
    textures = _nest_textures()
    for y, row_masks in enumerate(masks, top):
        wide_masks = tuple(_wide_mask(mask, span) for mask in row_masks)
        for sub_y in range(2):
            texture_y = (camera_y * 32 + (y - NEST_GRID_Y) * 2 + sub_y) % TEXTURE_SIZE
            start = ((2 * y + sub_y) * width + left) * 6
            end = start + span * 6
            for channel in range(3):
                values = pixels[start + channel:end:3]
                for texture, mask in zip(textures, wide_masks):
                    _paint(values, texture[texture_y][channel], mask, texture_x, 0, span)
                pixels[start + channel:end:3] = values
    return _ppm(width * 2, height * 2, pixels)


def render_hd(frame, payload, observation):
    """Encode a 2× frame with confirmed terrain and verified controls."""
    width, height = frame[:2]
    view = observation.get("edit")
    if (width, height) != (640, 480) or len(payload) != CAPACITY:
        raise ValueError("HD rendering requires a complete 640×480 scene sample")
    if observation.get("result") != "accepted" or view not in (SURFACE, NEST, RED_NEST):
        raise ValueError("HD rendering requires an accepted Surface, Black Nest, or Red Nest sample")
    if observation.get("terrain_layout") == TUTORIAL_NEST_LAYOUT:
        return _render_tutorial_terrain(frame, payload, observation)
    camera_x, camera_y = observation["camera"]
    east = observation.get("terrain_layout") == EAST_SURFACE_LAYOUT
    full = observation.get("terrain_layout") == FULL_SURFACE_LAYOUT
    full_panned = observation.get("terrain_layout") == FULL_PANNED_SURFACE_LAYOUT
    full_loaded = observation.get("terrain_layout") == FULL_LOADED_SURFACE_LAYOUT
    surface_raster_only = east or full or full_panned or full_loaded
    occupied_red = observation.get("terrain_layout") == OCCUPIED_RED_LAYOUT
    full_nest = observation.get("terrain_layout") == FULL_BLACK_NEST_LAYOUT
    if east and (view != SURFACE or not east_surface_camera(camera_x, camera_y)):
        raise ValueError("Unsupported east Surface camera")
    if full and (view != SURFACE or (camera_x, camera_y) not in FULL_SURFACE_CAMERAS):
        raise ValueError("Unsupported Full Game Surface camera")
    if full_panned and (view != SURFACE or not full_surface_camera(camera_x, camera_y)):
        raise ValueError("Unsupported panned Full Game Surface camera")
    if full_loaded and (view != SURFACE or (camera_x, camera_y) != FULL_LOADED_SURFACE_CAMERA):
        raise ValueError("Unsupported loaded Full Game Surface camera")
    if not (east or full_panned) and (not 0 <= camera_x < 64 or not 0 <= camera_y < 64):
        raise ValueError("Unsupported scene camera")
    red_masks = occupied_red_raster(frame) if occupied_red else None
    if occupied_red and (view != RED_NEST or (camera_x, camera_y) != OCCUPIED_RED_CAMERA or red_masks is None):
        raise ValueError("Unsupported occupied Red Nest raster")

    stride = 128 if view == SURFACE else 64
    first = payload[TERRAIN_START:TERRAIN_START + MAP_BYTES]
    second = payload[TERRAIN_START + MAP_BYTES:]
    full_nest_masks = None
    if full_nest:
        if view != NEST or not full_black_nest_camera(camera_x, camera_y):
            raise ValueError("Unsupported Full Game Black Nest camera")
        full_nest_masks = full_black_nest_raster(
            frame, first[:NEST_TERRAIN_BYTES], (camera_x, camera_y), tuple(observation["ant"][:2])
        )
        if full_nest_masks is None:
            raise ValueError("Unsupported Full Game Black Nest terrain")
    if view == SURFACE:
        detail_palette = SURFACE_STONE
        textures = (
            _texture((109, 95, 59), (78, 94, 55), 13, grass=True),
            _texture((113, 114, 108), (157, 160, 151), 29),
        )
    else:
        detail_palette = NEST_TUNNEL
        textures = _nest_textures()

    channels = _rgb_channels(frame)
    overlay = _has_neutral_overlay(channels)
    soil_masks = []
    if not overlay and not (occupied_red or full_nest):
        for y in range(TOP, BOTTOM):
            source = [channel[y * width + LEFT:y * width + RIGHT] for channel in channels]
            soil_masks.append(_surface_soil_row(source, y) if view == SURFACE
                              else _palette_mask(source, NEST_EARTH))

    pixels = bytearray(width * height * 12)
    output_row_size = width * 6
    tile_left, tile_top = (NEST_GRID_X, NEST_GRID_Y) if full_nest else (TILE_LEFT, TOP)
    texture_x = (camera_x * 32 + (LEFT - tile_left) * 2) % TEXTURE_SIZE
    tile_masks = (0, 0)
    for y in range(height):
        begin, end = y * width, (y + 1) * width
        rows = [values[begin:end] for values in channels]
        masks = (0, 0)
        if not overlay and occupied_red and RED_RASTER_TOP <= y < RED_RASTER_BOTTOM:
            masks = tuple(_wide_mask(mask) for mask in red_masks[y - RED_RASTER_TOP])
        elif not overlay and full_nest and NEST_PAINT_TOP <= y < NEST_PAINT_BOTTOM:
            masks = tuple(_wide_mask(mask) for mask in full_nest_masks[y - NEST_PAINT_TOP])
        elif not overlay and not (occupied_red or full_nest) and TOP <= y < BOTTOM:
            if not surface_raster_only and (y - TOP) % 16 == 0:
                tile_y = camera_y + (y - TOP) // 16
                tile_masks = _tile_masks(first, second, stride, tile_y, camera_x, view)
            source = [row[LEFT:RIGHT] for row in rows]
            soil = soil_masks[y - TOP]
            above = soil_masks[y - TOP - 1] if y > TOP else 0
            below = soil_masks[y - TOP + 1] if y < BOTTOM - 1 else 0
            if view == SURFACE:
                earth = _surface_ground_mask(soil, above, below, _palette_mask(source, ((0, 101, 16),)))
            else:
                isolated = (soil >> 8) & (soil << 8) & above & below
                earth = (soil | (_palette_mask(source, ((65, 65, 65),)) & isolated)) & tile_masks[0]
            scene_mask = NO_RESIZE_GRIP if y >= 362 else -1
            detail = 0 if surface_raster_only else _palette_mask(source, detail_palette) & tile_masks[1]
            masks = (
                _wide_mask(earth & scene_mask),
                _wide_mask(detail & scene_mask),
            )

        wide_rows = [_double(row) for row in rows]
        original = bytearray(output_row_size)
        for channel, values in enumerate(wide_rows):
            original[channel::3] = values
        if not any(masks):
            offset = y * output_row_size * 2
            pixels[offset:offset + output_row_size * 2] = original + original
            continue
        for sub_y in range(2):
            texture_y = (camera_y * 32 + (y - tile_top) * 2 + sub_y) % TEXTURE_SIZE
            painted = bytearray(output_row_size)
            for channel, original_values in enumerate(wide_rows):
                values = original_values.copy()
                for texture, mask in zip(textures, masks):
                    _paint(values, texture[texture_y][channel], mask, texture_x)
                painted[channel::3] = values
            offset = (y * 2 + sub_y) * output_row_size
            pixels[offset:offset + output_row_size] = painted
    if not overlay:
        if view == NEST and not full_nest:
            paint_nest_roots(pixels, frame, first, second, observation)
        paint_workspace(pixels, frame)
        if view == RED_NEST:
            if observation.get("terrain_layout") in ("legacy", "loaded"):
                paint_red_castes(pixels, frame)
            else:
                paint_red_queen(pixels, frame)
    if not overlay and not occupied_red:
        if view == SURFACE:
            paint_pebbles(pixels, frame, (LEFT, TOP, RIGHT, BOTTOM))
            paint_boulders(pixels, frame, observation, (LEFT, TOP, RIGHT, BOTTOM))
            paint_foliage(pixels, frame, (LEFT, TOP, RIGHT, BOTTOM))
            paint_food(pixels, frame, (LEFT, TOP, RIGHT, BOTTOM))
            paint_anthill_rim(pixels, frame, observation)
        paint_actors(pixels, frame, payload, observation)
        if view == SURFACE:
            paint_trails(pixels, frame, observation.get("scent_mode"))
        paint_ui(pixels, channels, width)
        paint_cursor(pixels, frame)
    return _ppm(width * 2, height * 2, pixels)
