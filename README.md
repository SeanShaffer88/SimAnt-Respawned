# SimAnt Respawned

Windows 11 remaster research for the English MS-DOS edition of SimAnt.

## Play on Windows 11 x64

1. Put the original pinned DOS archive at `inputs/reference.zip` and the pinned patched core at `inputs/dosbox_pure_libretro.dll`. The [reference replay](docs/reference/quick-game.md) identifies the archive. The [core patch](emulator/dosbox-pure/README.md) documents the core source, and [the host](tools/live_hd.py) specifies the required DLL SHA-256.
2. Use Windows x64 Python 3.11 or later with Tk. The launcher looks for `runtime/python.exe`, then the full interpreter path in `SIMANT_PYTHON`, then `python.exe` on PATH.
3. Open **Start SimAnt.cmd**. Dismiss the DOS startup prompts, select **Quick Game**, and press F11 to switch between Classic and HD in borderless fullscreen.

Native saves are stored in `data/profile` when you exit cleanly. Reopen the launcher and select **Load Game** to resume. Each launch uses its own folder in `data/runs`. Keep the inputs, saves, and run folders private because they can contain original game data. The pinned title snapshot is used for replay verification and is optional for direct command-line launch.

## Development References

- [DOS build fingerprint](docs/reference/dos-build.json)
- [Quick Game reference replay](docs/reference/quick-game.md)
- [Live DOS view probe](docs/reference/live-view-probe.md)
- [DOS terrain, ant position, and view-switch verification](docs/reference/scene-state-verification.md)
- [Synchronized DOS scene capture](docs/reference/synchronized-capture.md)
- [Live Classic and HD prototype](docs/reference/live-hd-prototype.md)

## Post-Revival Art Review

After the modern revival is complete, compare cel shading with a shortlist of other graphics styles. Prepare side-by-side image mockups of each candidate using the same Surface and Black Nest frames, camera bounds, and gameplay landmarks.
