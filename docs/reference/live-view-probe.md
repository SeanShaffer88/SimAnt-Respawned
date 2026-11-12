# Live DOS View Probe

The pinned English DOS 1.00 Quick Game exposes its active edit view through a guest-memory window reported by DOSBox Pure. This is the first observed field for a read-only scene bridge.

## Observed Field

DOSBox Pure supplied three Libretro memory descriptors. The eligible conventional-memory window had a length of 649,120 bytes and a mapped start of zero. A byte at offset `0x586E2` relative to that window reported `1` for Surface, `2` for Black Nest, and `3` for Red Nest. The probe copies the relevant descriptor data and reads that one byte. It pins the archive, DLL, and title snapshot before starting the core.

The interpretation was derived from View menu changes and cross-checked against the original visible views. The decoder reads the view from RAM. The replay actions supply the expected values for comparison.

| Action | Observed Value | Observed View |
| --- | ---: | --- |
| Reference frame 3000 | 2 | Black Nest |
| Reference frame 3165 | 1 | Surface |
| Open and cancel the View menu | 1 | Surface |
| Select Black Nest | 2 | Black Nest |
| Select Red Nest | 3 | Red Nest |
| Return to Surface | 1 | Surface |

## Run the Probe

Use the pinned files and Windows x64 Python setup in the [Quick Game replay instructions](quick-game.md). Run sequentially with a different unused output directory outside the checkout for each wait interval. The parent directory must exist.

```powershell
python -B .\tools\probe_scene_state.py `
  --archive 'C:\simant-reference\SimAnt_-_The_Electronic_Ant_Colony_1991.zip' `
  --core 'C:\simant-reference\dosbox_pure_libretro.dll' `
  --title-state 'C:\simant-reference\quick-game-title-start.state' `
  --out 'C:\simant-reference\view-probe-a' `
  --wait-frames 90
```

Repeat with `--wait-frames 137`. The 90- and 137-frame runs and the independent 181-frame run exited 0, with all six view checks and both original RGB hashes matching in each run. Each probe reports the decoded view to the console and records observations in `scene-state.json`. The output directory stays local because the generated DOS launcher ZIP contains the game. The recorded probe also compares the original RGB hashes at frames 3000 and 3165 with the observer enabled.

## Verification Boundaries

The tested field follows settled view selections on the pinned emulator and game build. DOSBox Pure can begin its next guest frame before the host call returns, so the observations establish settled view identity. They cannot establish atomic RAM and framebuffer snapshots during transitions.

Terrain, ant coordinates, scent overlays, visibility, and hit targets remain unverified. The console reports samples taken from live guest RAM. A graphical scene renderer remains unimplemented.

[Libretro memory map API](https://github.com/libretro/RetroArch/blob/master/libretro-common/include/libretro.h) · [DOSBox Pure memory-map and frame scheduling source](https://github.com/libretro/dosbox-pure/blob/e39497e7c2a32c67c26e6598dd14f6d58c384bfd/dosbox_pure_libretro.cpp)
