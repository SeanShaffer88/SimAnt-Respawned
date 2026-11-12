# Synchronized DOS Scene Capture

The DOSBox Pure patch copies configured guest-memory ranges at the finished software-frame boundary. The host retrieves the owned copy and pairs it with the video callback from that same core call. The Classic framebuffer still follows the original callback path.

The synchronization probe checks the three observed view fields, both terrain buffers, the Yellow Ant tile and layer, and camera coordinates. Because the original DOS game can draw its foreground and minimap in separate updates, a valid core capture can still contain a partial redraw. The verifier preserves the last accepted sequence when the current pair is incomplete or the observed scene fields disagree.

## Inputs

The experiment uses the English DOS 1.00 archive and title-screen snapshot identified by the [Quick Game reference replay](quick-game.md). The patch uses the pinned DOSBox Pure source revision `e39497e7c2a32c67c26e6598dd14f6d58c384bfd`. The unmodified Windows x64 build is a control for the effects of rebuilding the core.

## Reproduce

Build the [instrumented Windows x64 core](../../emulator/dosbox-pure/README.md). From the project root, supply the exact expected DLL SHA-256 and the local, hash-pinned game inputs. Each output directory must be new and outside the repository. Run the routes sequentially.

```powershell
$inputs = @(
    '--archive', 'C:\simant-reference\SimAnt_-_The_Electronic_Ant_Colony_1991.zip',
    '--core', 'C:\simant-reference\dosbox_pure_libretro.dll',
    '--core-sha256', '<SHA-256 of the trusted instrumented DLL>',
    '--title-state', 'C:\simant-reference\quick-game-title-start.state'
)
python -B .\tools\verify_synchronized_scene.py @inputs --route transitions --out 'C:\simant-reference\sync-transitions'
python -B .\tools\verify_synchronized_scene.py @inputs --route movement --out 'C:\simant-reference\sync-movement'
python -B .\tools\verify_synchronized_scene.py @inputs --route reference --out 'C:\simant-reference\sync-reference'
python -B .\tools\verify_synchronized_scene.py @inputs --route reference --capture-off --out 'C:\simant-reference\sync-reference-off'
```

The transition route verifies both native View-menu directions and the ant's actual layer change during emergence and descent. The movement route requires multiple visible ant positions on both layers. Both routes require the original opening RGB checkpoints and positive acceptance after the requested actions. Held frames keep the last accepted sequence. The reference route also verifies the sampled Game Over frame.

## Verification Results

The tested instrumented DLL had SHA-256 `5789d6d4e6c6fc15e3682db32301428a371b739a0ceaa189ecd1ede5df61e133`. The unmodified rebuild had SHA-256 `0c0f0ef2528843bf709d6eaf37c6fac006259a58e12e24eb9ac984345e410c83`. Both were built on Windows with MSVC 14.44.35207.

| Case | Observed Result |
| --- | --- |
| Surface to Black Nest via View menu | Both panes and the sampled terrain and view fields settled in Black Nest. |
| Black Nest to Surface via View menu | Both panes and scene fields settled on Surface while the Yellow Ant stayed underground. |
| Physical emergence | Yellow Ant layer changed from Black Nest to Surface at the original anthill. |
| Physical descent | Yellow Ant layer changed from Surface to Black Nest, settling at tile (31, 1). |
| Yellow Ant movement | Multiple visible positions matched the projected tile on each layer. |
| Publication | All 58 classified mixed samples were held across the two final routes. No rejected sample advanced the published sequence. |

The sequential reference replay compares exact decoded RGB at core calls 3000 (Black Nest), 3165 (Surface), and 20000 (Game Over). In these runs, all three matched the pinned original binary, the unmodified local build, and the instrumented build with capture enabled and disabled. The [prior replay limits](quick-game.md#verification-boundaries) still apply to other starting states and concurrent runs.

## Scope

This is a read-only capture and verification path for the pinned Quick Game fixture. The checked classifiers describe the original 640×480 window arrangement and observed terrain classes. The HD renderer remains a separate milestone. The game archive, guest snapshots, generated PNGs, and DLLs stay outside the repository.
