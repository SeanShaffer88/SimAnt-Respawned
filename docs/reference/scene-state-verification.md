# DOS Scene State Verification

This experiment used the pinned English DOS 1.00 game, DOSBox Pure 1.0-preview8, and the saved title-screen origin from the [Quick Game reference replay](quick-game.md). The observer replayed original mouse actions, read guest memory, and compared decoded fields with the original DOS framebuffer. The production HD renderer remains on hold because a view switch can expose a mixed scene.

## Surface Terrain

Two guest-memory regions showed the same visible 39×64 minimap slice. The slice begins at program-relative offsets `0x6E6D9` and `0x84649`. Both use a 128-byte row stride. Byte 11 matched brown ground and byte 13 matched gray rock.

| Capture | Brown Ground | Gray Rock | Other or Overlay | Classified Matches per Buffer |
| --- | ---: | ---: | ---: | ---: |
| Reference Surface, frame 3165 | 2,280 | 205 | 11 | 2,485 of 2,485 |
| After the Yellow Ant emerged, frame 3906 | 2,279 | 205 | 12 | 2,484 of 2,484 |

The captures came from the same Quick Game patch. This verifies the two display classes in the sampled minimap slice. The two copies remain indistinguishable, and the authoritative terrain structure and other tile classes remain open.

## Black Nest Terrain

The two view buffers start at `0x6E6C0` and `0x84630` with a 64-byte row stride in the Black Nest view. A native double-click caused the Yellow Ant to dig at tile (38, 12). The same tile stayed open after the ant emerged and the player returned to the Black Nest view. Its 16×16-pixel screen area was compared after accounting for camera movement.

| Frame | Tile Byte in Both Copies | Solid-Brown Pixels |
| --- | ---: | ---: |
| 3430, before digging | 10 | 224 of 256 |
| 3738, with the Yellow Ant on the new opening | 1 | 41 of 256 |
| 4434, after the ant left | 12 | 39 of 256 |

The captured change verifies a persistent tunnel at the sampled position. The middle code coincides with the Yellow Ant overlay. Both buffers can contain a composite of terrain and actors.

## Yellow Ant Position

The sampled Yellow Ant fields were little-endian 16-bit values at program-relative offsets `0x515FC` (X), `0x5160A` (Y), and `0x5160C` (layer, 1 for Surface and 2 for Black Nest). Each coordinate advanced 16 screen pixels per tile at a fixed camera. Independent matching of surface rock landmarks found a (+16, +16) camera translation between emergence and the walking captures.

| Settled Capture | Guest Tile | Layer | Projected Screen Position |
| --- | --- | --- | --- |
| Nest, idle | (37, 11) | Black Nest | (247, 209) |
| Nest, after walking | (35, 9) | Black Nest | (215, 177) |
| Nest, after digging | (38, 13) | Black Nest | (295, 257) |
| Surface, after emerging | (32, 31) | Surface | (231, 209) |
| Surface, after eastward walk | (36, 26) | Surface | (311, 145) |
| Surface, after westward walk | (29, 34) | Surface | (199, 273) |

Every projected point fell inside the independently measured yellow sprite bounds. A View-menu trip to Black Nest and back left the ant at (29, 34), on Surface, while the displayed view changed. The ant was absent from the nest viewport.

Camera X and Y were little-endian 16-bit values at `0x51688` and `0x5168A`. The same projection worked on both layers across both runs. Independent registration of rock and tunnel landmarks agreed with the camera changes.

```text
screen_x = 71 + 16 * (ant_x - camera_x)
screen_y = 49 + 16 * (ant_y - camera_y)
```

The second run tested a different route and camera positions. The projected point fell inside the original sprite bounds at all five additional settled captures: two in the nest, one at emergence, and two after Surface movement. The original two RGB replay anchors also matched with the observer enabled.

During the eastward walk, one captured sprite was still at the previous tile (32, 31) while RAM already showed (33, 30). The camera had settled. The projected point was (263, 209), while the sprite occupied x242–253 and y224–226. This rules out treating a live RAM read and the last video frame as an interchangeable position sample.

## View Switches

Frame numbers count frontend `retro_run` calls. The first trace compares the original video toolbar with the previously verified settled-view byte at `0x586E2` after each call. A non-null video callback can repeat previous pixel data.

| Action | Different View Labels | Calls with a Difference |
| --- | ---: | --- |
| Yellow Ant emerges | 1 of 175 classified | 3892 |
| View menu selects Black Nest | 4 of 65 classified | 4379–4382 |
| View menu selects Surface | 15 of 64 classified | 4490–4504 |

One additional Surface-selection call had an unclassified repaint. Direct inspection of the original frames confirmed mixed views at two boundaries. At 3892, the main viewport already displayed the Surface with the Yellow Ant beside the anthill, while the map still showed the nest. At 4379, the viewport already showed the tunnel, while the map still showed Surface terrain. The byte from the settled-view probe lagged the foreground in both cases. Frame 3892 also returned different view bytes in two host reads with no intervening `retro_run`.

A second run classified the foreground by terrain pixels and checked the minimap separately. During emergence the Surface foreground appeared at 3951. The view byte switched at 3952, the sampled terrain bytes finished changing at 3955, and the map first classified as Surface at 3960. During a View-menu switch to Black Nest, the foreground changed at 4761, the view byte at 4773, and the map and both terrain samples at 4775. This produced 12 classified foreground/view-byte mismatches at 4761–4772 and 14 mixed foreground/map calls at 4761–4774. The two alternative RAM view fields also changed at different calls. A physical descent did not occur in these captures, so that case remains untested.

The inspected core source can resume the guest before dispatching video. It provides no guaranteed read boundary that pairs the published framebuffer with the matching guest bytes. Even a core-owned pause must account for the original game redrawing the viewport and minimap separately. The renderer needs a coherent snapshot of the view, terrain, and Yellow Ant, with partial transitions held until they agree. [DOSBox Pure frame scheduling source](https://github.com/libretro/dosbox-pure/blob/e39497e7c2a32c67c26e6598dd14f6d58c384bfd/dosbox_pure_libretro.cpp)
