# DOSBox Pure Scene Capture

This GPL-2.0-or-later patch applies to [DOSBox Pure 1.0-preview8 at e39497e](https://github.com/libretro/dosbox-pure/commit/e39497e7c2a32c67c26e6598dd14f6d58c384bfd). The full license is in [COPYING](COPYING). The original game and emulator binaries are supplied separately.

## Windows x64 Build

Use Visual Studio Build Tools with the C++ x64 workload and Windows SDK. The tested local toolchain used Visual Studio 2022 Build Tools and MSVC 14.44.35207. In a separate upstream checkout, apply this patch and invoke MSBuild from a Developer PowerShell.

```powershell
git clone https://github.com/libretro/dosbox-pure.git
Set-Location dosbox-pure
git checkout --detach e39497e7c2a32c67c26e6598dd14f6d58c384bfd
git apply --check $scenePatchPath
git apply $scenePatchPath
MSBuild.exe dosbox_pure_libretro.sln /nologo /m /p:Configuration=Release /p:Platform=x64 /v:minimal
```

Set `$scenePatchPath` to the absolute path of `0001-scene-capture.patch` before running these commands. The solution produces `build/Release_64bit/dosbox_pure_libretro.dll`.

## Frontend Contract

The patch adds two opt-in C ABI exports. Call them on the frontend thread that owns the Libretro session, outside Libretro callbacks.

```c
bool retro_set_scene_capture_v1(const uint32_t *offset_lengths, uint32_t range_count);
uint32_t retro_get_scene_capture_v1(uint8_t *destination, uint32_t capacity,
                                    uint64_t *sequence, uint32_t *width, uint32_t *height);
```

- Configure up to eight ranges, each supplied as an offset followed by a nonzero length in bytes. Offsets are relative to the program-memory region reported by Libretro with guest start zero in DOSBox Pure's non-boot mode. The total length is capped at 32 KiB. Invalid configuration leaves the previous configuration intact. A zero range count disables capture.
- During `retro_run`, the core validates the configured ranges against the reported program-memory region. It copies their bytes while the emulator is stopped at a finished frame, after selecting the software video buffer and before waking the guest. Skips, duplicate draws and hardware video produce no capture. Existing Libretro video delivery continues normally.
- After `retro_run`, the frontend pairs a successful capture with the software frame delivered in that same call. The getter copies bytes in range order and returns the number copied, the draw dimensions and a monotonically increasing capture sequence for the session. The getter returns zero for an unavailable capture, a null output pointer or insufficient capacity. It can be called again before the next `retro_run`.
- Starting a run, reconfiguring, resetting or restoring invalidates the prior capture. Reset and restore wait for a draw newer than the one before the state change. Unload and deinitialization clear the configuration and sequence.

The pause boundary aligns the RAM sample with the core's selection of the video buffer. The game can still update its own scene over several draws. The frontend must evaluate view, terrain and actor coherence before forwarding a snapshot to an HD renderer.
