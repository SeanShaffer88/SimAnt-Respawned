# Live Classic and HD Prototype

This Windows prototype opens in borderless fullscreen and runs the pinned SimAnt DOS Quick Game in one DOSBox Pure session. The game is centered at a whole-number scale. F11 and the display button switch the host presentation. Both modes use the original coordinate system and guest inputs. Use Quit or Alt+F4 to close the host.

HD uses the synchronized capture to redraw verified Surface and Black Nest terrain at twice the original resolution. It preserves the original controls, minimap, and entities. The current Classic frame remains available whenever the scene cannot be verified or an unsupported view is active.

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

The Windows reopen check restored the saved view, camera, and Yellow Ant position, then resumed gameplay with the original Pause control. The tested loaded Surface and Black Nest did not match the current HD terrain capture ranges after resuming and switching views. The HD selection displayed the native Classic frames in both views. HD terrain capture for loaded games remains open.

## Verify

```powershell
python -B .\tools\verify_live_hd.py @inputs --out 'C:\simant-reference\verify-hd'
```

This runs paired serial replays with identical guest inputs and core call counts. The switching replay composes both HD scenes and checks that presentation leaves the original framebuffer and selected scene state unchanged. The reference route checks the original Black Nest, Surface, and Game Over RGB anchors. The interaction routes cover both View menu directions, emergence, descent, and Yellow Ant movement. Unclassified states use Classic.

## Verified Results

The Windows 11 x64 Tk smoke opened a 1920×1080 native borderless window with no caption or resize frame. The 1280×960 game image was centered below the toolbar. Clicks mapped back to the original DOS coordinates. F11 and the display button switched presentation at the same guest call with the same mouse state. The smoke displayed both HD scenes.

Six serial replay processes passed across three routes. Their 31 switches left ordered guest input and core call counts identical to Classic-only controls. All 16 sampled original frame and decoded scene observations matched. The 15 accepted visible terrain samples matched both raw tile pairs within the Edit pane. Larger raw mailbox spans differed at all 16 paired observations. They also varied between Classic-only runs. The result establishes parity for the sampled fields and original RGB, with broader memory equivalence unverified.

The exact original RGB checkpoints at calls 3000, 3165, and 20000 matched in the paired reference replay. Game Over displayed in Classic while HD was selected.

## DOS Audio

The fullscreen launcher sends the core's original signed 16-bit stereo audio to the default Windows playback endpoint at the negotiated rate. The pinned core uses 48 kHz. The same audio stream stays attached through Classic and HD switches. SimAnt's original Options menu controls the game's sound.

A WinMM worker waits for queued samples, device completion, and shutdown events. It keeps up to 80 ms pending and four reusable 20 ms device buffers. A full queue drops excess samples to protect the emulator clock. If the endpoint cannot start, the game continues and logs the audio error.

On Windows 11, the default endpoint naturally completed all 222,720 submitted frames with zero drops or device errors in the paced smoke. A paired Quick Game transition replay preserved the original opening RGB hashes, input sequence, and 4,287 core calls with audio active. Both runs delivered 3,111,888 PCM frames. Raw waveform hashes varied across Classic-only repeats as well as the switching run. A separate 20,000-call paired replay matched all three original RGB checkpoints with audio enabled and disabled.

## Prototype Limits

The renderer redraws verified terrain and retains the original sprites and interface. Replay evidence applies to the pinned DOS build and Quick Game fixtures.
