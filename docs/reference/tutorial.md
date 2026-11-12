# DOS Tutorial First-Dig Replay

The original Tutorial starts in the Black Nest. The replay advances the native guidance, dismisses the final prompt, and double-clicks to dig. The Yellow Ant moves from `(37, 11)` to `(39, 12)` and opens two new tunnel tiles. The final replay step parks the pointer to expose the original ant and floor pixels.

| Checkpoint | Core call | Native RGB SHA-256 |
| --- | ---: | --- |
| Game selector | 487 | `2636b9845e52a172483461e2176b853b3f3238974ad90aefd67c802c2711b7ca` |
| Tutorial selected | 553 | `9b5003d878d7d5bc8da360bf20c6ddf2f4edbb67944d3f20fbbe5cf72716051a` |
| Welcome | 673 | `fb65e92da828cffe5e8e37d3a1f12e7e72b772674138dd6a2ba2af8209911274` |
| First guidance | 859 | `65463610041200c6b5de35418b74e8af2aa8b91c103b54309ae6bc8c3170d21b` |
| Final guidance | 1045 | `e36035d81650f549a2b14de2c1c34ef8c731e4b28bcf756d82cd9507d34fc808` |
| Prompt dismissed | 1086 | `13479fea2b424d5763fa312fb69f8c976c0817a4bb050c8a5f5949387884d515` |
| First dig | 1280 | `82ecf0cd32eb469ff9ab6c0db66d7fbe843a5182d7ccda763309f434c2a4fef5` |
| Pointer parked | 1285 | `b9a8fe159435316ec4935e2cc900c578e34f3729e1d405466cebd71e60343165` |

## Run on Windows 11 x64

Use Python 3.11 or later, the original DOS archive from the [build fingerprint](dos-build.json), the private [title snapshot](quick-game.md), and the pinned [instrumented DOSBox Pure core](../../emulator/dosbox-pure/README.md). Run from the repository root with a new output directory outside the checkout.

```powershell
python -B .\tools\verify_tutorial.py `
  --archive 'C:\simant-reference\reference.zip' `
  --core 'C:\simant-reference\dosbox_pure_libretro.dll' `
  --title-state 'C:\simant-reference\quick-game-title-start.state' `
  --out 'C:\simant-reference\verify-tutorial'
```

The verifier starts two fresh DOS processes in order. Both must match the pinned 885 input records, eight native RGB anchors, view bytes, camera, and Yellow Ant position. It independently compares native soil and floor pixels with the two captured terrain copies. The final guidance and the first-dig frame must display exact Classic pixels when HD is requested. After the prompt closes and after the pointer is parked, HD must change at least eight source pixels in each of two confirmed soil tiles and two confirmed floor tiles. Tiles near the ant or pointer and outside the verified playfield are excluded. Switching each HD checkpoint back to Classic must restore the original pixels with the same core call and guest state.

Each trial writes local PNGs, input logs, and captures. The paired `verification.json` records pass or failure. Full mailbox hashes help diagnose differences between processes. The verifier uses the selected state and verified terrain as the cross-process comparisons. The scope covers the first dig in the pinned maximized Tutorial pane. Keep output local because it contains the generated DOS launch archive.
