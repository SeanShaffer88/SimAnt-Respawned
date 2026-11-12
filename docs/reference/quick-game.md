# DOS Quick Game Reference Replay

The reference is the archived English DOS installation of Maxis SimAnt. The executable identifies itself as 1.00 with the build stamp `Fri Dec 06 14:51:14 1991`. The [build fingerprint](dos-build.json) pins the ZIP and all 17 file entries. Equivalence to a retail floppy image remains unverified.

## Recorded Route

The replay starts at the original title screen before any player input. It dismisses the opening screens, selects Quick Game, and lets the first Yellow Ant mature. It captures the Black Nest, selects Surface in the original View menu, then selects Ultra in the original Speed menu and waits. The original Game Over screen shows **418,588** and **Weak Link in the Food Chain**.

| Checkpoint | Core Frame | SHA-256 of Decoded RGB Pixels |
| --- | ---: | --- |
| Black Nest | 3000 | `d7bf1756260d55efee501ab802fff39ba1e7b34ac04037dda83cf374f1066754` |
| Surface | 3165 | `5369f6fa56fc1726f35e0b81f908db6c2048c5305f4b503dbb2f406041458f27` |
| Game Over | 20000 | `b59466ab87b5b5464386f0abd510d82cc4299de3441fb3518bc46d4b9837184d` |

Core frames count libretro `retro_run` calls. The game ended by frame 20000. The precise end frame was outside this capture.

## Reproduce

The Windows x64 runner uses Python 3.11 or newer. The recorded checks used Python 3.15.2 on Windows 11 build 26300. It loads DOSBox Pure 1.0-preview8 with 4720 fixed cycles and the normal CPU core. The runner verifies the archive, DLL, and any provided snapshot by SHA-256 before loading the DLL. The original captures are 640×480.

- Use the archive from the [build fingerprint](dos-build.json).
- Use the x64 Libretro DLL with SHA-256 `c43967d99ceb40294ccd5c0847185f46e868ac7479de1ca96fad788e5ae1f27c`. The [Libretro Buildbot ZIP](https://buildbot.libretro.com/nightly/windows/x86_64/latest/dosbox_pure_libretro.dll.zip) used here had SHA-256 `e4d03b37e19f7595b0a693aced6ba765336cbc09a9e5cbd9546628c2e0663333`. This endpoint rolls forward. Retain the hash-matched copy for later replays.
- The full replay restores the private frame-400 title snapshot (1,718,923 bytes, SHA-256 `cf279cc96f03d1253fbe03cf6ce3be289f1e8f8974cc8906880dee493e472f49`). The snapshot and generated DOS launcher ZIP contain original game data and stay in local scratch.

From the repository root, substitute local input paths and an unused output directory outside the checkout. Its parent must exist.

```powershell
python .\tools\replay_quick_game.py `
  --archive 'C:\simant-reference\SimAnt_-_The_Electronic_Ant_Colony_1991.zip' `
  --core 'C:\simant-reference\dosbox_pure_libretro.dll' `
  --title-state 'C:\simant-reference\quick-game-title-start.state' `
  --out 'C:\simant-reference\replay-a'
```

The runner saves a trace of inputs and expected and actual frame hashes. Run again sequentially with a different output directory to compare results. See the [recorded input trace](quick-game-trace.json). Omit the title state argument to validate only the cold-start opening. The cold run saves the later frame as an informational terminal probe.

## Verification Boundaries

Two sequential restores of the same title snapshot exited 0 and reproduced all three checkpoints. Their traces matched byte for byte (SHA-256 `1ffa87cbce605c3423927507f3679550d163278c8e1ac4d7ab15736679dc534c`). A concurrent invocation using the same snapshot still showed the black queen death notice at frame 20000. A fresh cold run without a snapshot showed the red ants attacking at that frame. The two opening frames matched in both divergent runs. The cause of the timing variation remains unverified. The strict check returns a nonzero exit code when the terminal image diverges.

This evidence covers one recorded DOS match on the pinned host profile. A win, additional starting states, save and resume, and other Quick Game interactions still need replay cases. The HD images are static art concepts based on the two scene captures. A live HD renderer and a candidate parity comparison remain future work.

## Sources

- [Internet Archive English DOS reference package](https://archive.org/details/msdos_SimAnt_-_The_Electronic_Ant_Colony_1991)
- [Original DOS manual](https://www.bestoldgames.net/download/games/simant/simant-dos-manual.pdf)
- [DOSBox Pure core documentation](https://docs.libretro.com/library/dosbox_pure/)
