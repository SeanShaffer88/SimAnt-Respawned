# Live Classic and HD Prototype

This Windows prototype opens in borderless fullscreen and runs the pinned SimAnt DOS Quick Game in one DOSBox Pure session. The game is centered below the toolbar at the largest whole-number scale that fits, up to 4×. Classic and HD share the same image bounds and native mouse coordinates. F11 and the display button switch the host presentation. Use Quit or Alt+F4 to close the host.

HD uses the synchronized capture to redraw verified Surface, Black Nest, and Red Nest terrain at twice the original resolution. The game keeps its original controls, minimap, and entity positions. The current Classic frame remains available whenever the scene cannot be verified or an unsupported view is active.

The terrain textures add muted grass and loam, fine stone and soil detail, and warmer tunnel floors. The texture coordinates stay fixed to the map as the camera moves. In a verified Surface view, the original checkerboard phase and matching neighbors confirm soil across the Edit pane, including beyond column 63. An isolated green fleck requires matching soil on all four sides. Rocks and regular underground terrain use verified tile and source-pixel masks to preserve their original boundaries. The Red Nest uses its own selected toolbar control and the underground minimap. Its ants retain their native sprites.

At the Red Nest entrance on the verified [Quick Game victory route](quick-game-win.md), HD can redraw exact soil and tunnel pixels from the synchronized native frame while the Yellow Ant is underground. This requires the original camera, a matching full Yellow Ant pose, a clear cursor, Scent Off, and enough intact tunnel pixels. The entrance redraw keeps the original foreground and controls. The queen death notice and victory dialog use Classic pixels.

The HD Yellow Ant follows nine verified native silhouettes across all eight headings. The Black Nest redraw covers the labeled Black Queen silhouette, three verified worker movement poses, and two verified soldier movement poses. Workers use charcoal with silver highlights. Soldiers use warmer bronze highlights. The DOS game determines when each pose appears. Each redraw follows the exact native pixels of the matching pose, and unmatched or occluded poses retain the DOS artwork.

When the Black Nest view is confirmed but its terrain is unconfirmed, HD can still redraw verified workers and soldiers over the doubled native frame. The DOS menu bar must match the resting menu, and the Edit pane must be clear of overlays.

The HD top menu bar and resting Map, Help, utility, Pause, and Scent controls use a higher-contrast palette. Open File, Window, View, Options, and Speed menus also use this palette when their original header, border, and colors match. The Scent flyout uses teal for the selected or hovered row and lighter fills behind the remaining labels. Native icons and labels identify the scent modes, and the DOS game determines the selected row and each control's hit area. Dialogs and unmatched menu regions retain their native pixels.

In the Surface B-Trail scent view, complete native Black Trail patterns appear as clearer colored marks with distinct intensities. Partial or ambiguous patterns and other scent modes keep their DOS pixels.

On the Surface, stationary food clusters that match the verified native pattern gain brighter green highlights and olive edges. The redraw uses the native silhouette and position. Clipped clusters and clusters covered by another object retain their DOS artwork.

The HD Surface also shades three verified pebble shapes with cool highlights and warm granite tones. Only the original gray pixels are redrawn. The original silhouettes, black shadows, and grid positions are retained.

Two verified Surface foliage sprites use subdued green accents in HD. The grass tuft and fern keep their native shape, position, and shadows. Clipped or obscured foliage keeps its original artwork.

A panned east Surface frame can use HD when the visible native minimap outline, every classified terrain sample in the full minimap slice, and the projected Yellow Ant pose all agree. The terrain witness is the second legacy buffer. The east redraw uses the original ground pattern and verified food and pebble silhouettes. Unconfirmed east terrain retains its DOS artwork.

HD redraws a fully matched DOS arrow with an ivory face, charcoal edge, and amber accent at the tip. The 2× redraw stays within the original arrow's opaque pixels. The DOS game still controls cursor position and hit testing. Classic presentation and frames with clipped or ambiguous cursors retain the native arrow.

In a verified HD scene, the default DOS window arrangement can use a slate-teal desktop backdrop. The redraw follows the native exterior and checks the window rails before painting. Window contents, borders, and native cursor coverage retain their original positions.

## Local Inputs

Use 64-bit Windows Python with Tk and the [instrumented DOSBox Pure core](../../emulator/dosbox-pure/README.md). The [reference replay](quick-game.md) records the original game and title-snapshot hashes. Keep the local game and DLL outside the repository. The scratch directory can contain original game data.

## Start

From the repository root, substitute the local inputs and a new scratch directory whose parent exists.

```powershell
$inputs = @(
    '--archive', 'C:\simant-reference\SimAnt_-_The_Electronic_Ant_Colony_1991.zip',
    '--core', 'C:\simant-reference\dosbox_pure_libretro.dll',
    '--title-state', 'C:\simant-reference\quick-game-title-start.state'
)
python -B .\tools\live_hd.py @inputs --out 'C:\simant-reference\play-01' --save-dir 'C:\simant-reference\saves'
```

Dismiss the original startup prompts and select Quick Game. F11 switches between Classic and HD during play. The display bar shows when the requested HD mode is using the current Classic frame. The DOS menus and mouse controls remain available in both modes.

## Save and Resume

Use **File > Save As** in SimAnt to name a new save, then click **Save**. Use Quit or Alt+F4 to close the host and commit the DOS save archive. For the next launch, reuse the same `--save-dir` and choose a new `--out` directory. Dismiss the original startup prompts and select **Load Game** from the game selection dialog. Select the `.ANT` file and click **Load**. The original game opens paused. Bring Edit to the foreground and click **Pause** in the Edit toolbar to resume. Both display modes use the same saves.

One running instance owns each save directory. DOSBox Pure works on a copy under the run's scratch directory. After a clean close, the host checks the new archive and replaces the profile copy only when it has changed. A failed run or failed update leaves the prior profile in place. Keep both directories local because they can contain original game data. A launch without `--save-dir` keeps its saves in that run's scratch directory.

The pinned DOS game places its terrain buffers at different addresses after a native Quick Game load. The frontend captures both layouts at the same video boundary and uses the first layout whose two terrain copies agree with the scene. For the loaded Surface layout, verification samples the upper 51 minimap rows because the Caste Control window can cover the lower rows. Both buffers must match every classified sample, with at least 1,800 samples. Mixed or unconfirmed scenes still display Classic.

## Verify

```powershell
python -B .\tools\verify_live_hd.py @inputs --out 'C:\simant-reference\verify-hd'
python -B .\tools\verify_loaded_quick_game.py @inputs --out 'C:\simant-reference\verify-loaded'
```

This runs paired serial replays with identical guest inputs and core call counts. The switching replay composes both HD scenes and checks that presentation leaves the original framebuffer and selected scene state unchanged. The reference route checks the original Black Nest, Surface, and Game Over RGB anchors. The interaction routes cover both View menu directions, emergence, descent, and Yellow Ant movement. Unclassified states use Classic.

The loaded-game verifier uses separate processes to save a Quick Game through the original **Save As** dialog and reopen it through **Load Game**. It checks the saved view, camera, and Yellow Ant position, then resumes through the original Pause control. It checks that Surface and Black Nest paint distinct HD terrain, toggles each back to exact Classic pixels at the same core call, and confirms that the original framebuffer, guest input, and captured state stay identical through both presentation changes. It also verifies that the Yellow Ant can move afterward and that reopening leaves the save archive byte-identical. Keep the verification output outside the repository because it contains the native save.

## Verified Results

The Windows 11 x64 Tk smoke opened a 1920×1080 native borderless window with no caption or resize frame. The 1280×960 game image was centered below the toolbar. Clicks mapped back to the original DOS coordinates. F11 and the display button switched presentation at the same guest call with the same mouse state. The smoke displayed both HD scenes.

Six serial replay processes passed across three routes. Their 31 switches left ordered guest input and core call counts identical to Classic-only controls. All 16 sampled original frame and decoded scene observations matched. The 15 accepted visible terrain samples matched both raw tile pairs within the Edit pane. Larger raw mailbox spans differed at all 16 paired observations. They also varied between Classic-only runs. The result establishes parity for the sampled fields and original RGB, with broader memory equivalence unverified.

The exact original RGB checkpoints at calls 3000, 3165, and 20000 matched in the paired reference replay. Game Over displayed in Classic while HD was selected.

## DOS Audio

The fullscreen launcher sends the core's original signed 16-bit stereo audio to the default Windows playback endpoint at the negotiated rate. The pinned core uses 48 kHz. The same audio stream stays attached through Classic and HD switches. SimAnt's original Options menu controls the game's sound.

A WinMM worker waits for queued samples, device completion, and shutdown events. It keeps up to 80 ms pending and four reusable 20 ms device buffers. A full queue drops excess samples to protect the emulator clock. If the endpoint cannot start, the game continues and logs the audio error.

On Windows 11, the default endpoint naturally completed all 222,720 submitted frames with zero drops or device errors in the paced smoke. A paired Quick Game transition replay preserved the original opening RGB hashes, input sequence, and 4,287 core calls with audio active. Both runs delivered 3,111,888 PCM frames. Raw waveform hashes varied across Classic-only repeats as well as the switching run. A separate 20,000-call paired replay matched all three original RGB checkpoints with audio enabled and disabled.

## Prototype Limits

Terrain, sprite poses, scent patterns, and control states outside the verified set retain the original DOS presentation. Replay evidence applies to the pinned DOS build and Quick Game fixtures.
