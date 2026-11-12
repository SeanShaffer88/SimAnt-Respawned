# DOS Quick Game Victory Replay

The replay starts from the pinned title snapshot and follows the original Quick Game opening. Native mouse input moves the Yellow Ant out of the Black Nest, across the yard, and through the Red Nest entrance. The Yellow Ant reaches the queen by following the tunnel. At core call 6550, the original game reports that the red queen died. At call 6656, the original victory dialog appears after the first notice is dismissed. [Original SimAnt DOS manual](https://www.bestoldgames.net/download/games/simant/simant-dos-manual.pdf)

| Checkpoint | Core Call | Native RGB SHA-256 |
| --- | ---: | --- |
| Emergence and presentation switch | 3906 | `a82d52eea5232040ce8872d8e507bcd3db1ffef788e4a0988fa7adc79cdbfa24` |
| Eastern Surface | 4981 | `431cd28566c57b4a8fee3b1d4ab81b5b6cda2e681602aadd4f17675aa4e1adb6` |
| Red Nest entry | 5722 | `e45146b60094f0df5469a00cda6999c198b117f2b3a8577dbc9038f301d3f7a2` |
| Queen approach | 5856 | `de5d65283fa1df12ea2e90e16ba8e5b7ae0bbd9976dc2f830ee7c77055572178` |
| Queen fight | 6100 | `6f9ea83e24e0bcfdbe6638659ccc136c87ce6dbde8c1a45a7471315afde743d3` |
| Queen death notice | 6550 | `9bb7439be21c3a378ba959c98d4b1cce14ca17abb776f0aa9b166dc4a16a6084` |
| Victory and return to Classic | 6656 | `2ed64877483ec5673ab868439439ae5efe63cc392e20f3dbf147b4406e063b77` |

## Run on Windows 11 x64

Use Python 3.11 or later, the original DOS archive from the [build fingerprint](dos-build.json), and the private title snapshot from the [reference replay](quick-game.md). Use the pinned [instrumented DOSBox Pure core](../../emulator/dosbox-pure/README.md). Run the command from the repository root with local input paths and a new output directory outside the checkout.

```powershell
python -B .\tools\verify_quick_game_win.py `
  --archive 'C:\simant-reference\reference.zip' `
  --core 'C:\simant-reference\dosbox_pure_libretro.dll' `
  --title-state 'C:\simant-reference\quick-game-title-start.state' `
  --out 'C:\simant-reference\verify-quick-game-win'
```

The verifier starts two fresh DOS processes in order. Both replay the same 38 direct inputs and 2,750 queued steps over 6,656 core calls. The switching run uses the host's presentation switch directly and verifies that the HD pixels at emergence differ from a simple upscale. It shows the original DOS victory dialog while HD is requested, then switches to exact Classic pixels at the same core call. The verifier compares all nine observations, the two pinned opening anchors, and the captured scene state. It exits nonzero for an exact comparison failure.

Each trial saves its input logs and PNGs under the output directory. The paired `verification.json` records the comparison. Keep the output local because it contains the generated DOS launch archive. This route qualifies the pinned match and snapshot. The [reference replay](quick-game.md) covers the passive loss path, and the [live prototype verifier](live-hd-prototype.md#verify) covers save and reopen.
