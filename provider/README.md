# Vela FSR 4 provider for Vulkan: complete corresponding source

`upscale/assets/sgsr3/amd_fidelityfx_upscaler_vk.dll` in the Vela 0.8.21 zip is built from this folder. The build is reproducible: it fixes the image
base of the DLL, pins the MinGW packages and checks the Vulkan-Headers commit. `build.sh` prints the md5 of the DLL.

## License
- Provider code (fsr4vk's own code and the Vela changes in `overlay/`): **GPL-3.0** (`fsr4vk/LICENSES/GPL-3.0.txt`).
  fsr4vk is not MIT: its README says the repository has no single license; its own code is GPL-3.0.
- AMD FSR 4.1.1 INT8 and FSR 4.1.2 Lite shaders and weights (`vela_assets/fsr411/`, `overlay/ov/vela-fast-spv.hpp`,
  `overlay/ov/vela-baked-pre.hpp`, `overlay/ov2/fsr412lite-blobs.hpp`, `overlay/gen/fsr4fu-spv.hpp`):
  AMD's MIT license, notice and origin in `../plugin/assets/licenses/fsr4vk/AMD-FidelityFX-SDK-MIT.md`.
- FFX API headers (`fsr4vk/amd-fidelityfx-sdk/`): AMD MIT (`fsr4vk/LICENSES/AMD-FidelityFX-SDK-MIT.md`, SDK 2.0.0 text).
- SR4 skipped-frame kernels (`overlay/gen/fsr4sr4-spv.hpp`, source in `sr4-kernels/`): GPL-2.0-or-later (rules from fsr4-shader-performance-overrides).
- Our own GLSL (`spirv-sources/fv`, `spirv-sources/npu`): GPL-3.0.
- Zstandard decoder (`fsr4vk/third_party/zstd`): BSD.

**No FSR 4.0.2 material**: this release build neither contains nor accepts the FSR 4.0.2 model. fsr4vk's 4.0.2 bundles
(`assets/general`, `assets/portable`, `assets/colors`) and its own `assets/fsr411` (replaced by Vela's modified copy in
`vela_assets/fsr411`) and `native/validation-data` are left out of `fsr4vk/` here; the build does not use them.

## What is where
| folder | content |
|---|---|
| `fsr4vk/` | https://github.com/dvj5411/fsr4vk at commit `391f62b` ("Delete provider/NATIVE-INPUTS.md"), files unchanged, without the folders above |
| `overlay/ov`, `overlay/ov2` | Vela's changed provider files (copied over `fsr4vk/native` and `fsr4vk/provider/ffx_vk_provider.cpp` by the build): FSR 4 Fast, its 1.5x mode for 1080p Ultra Performance, the NPU path (`fv_npu.hpp`), FSR 4.1.2 Lite, and the release change `build/prv_overlay.py` describes (no 4.0.2) |
| `overlay/gen` | generated SPIR-V headers: Lite NPU pack/unpack, fused kernels, SR4 kernels |
| `sr4-kernels/` | GLSL source, generators and build of the SR4 skipped-frame kernels (`sh sr4-kernels/build.sh`) |
| `spirv-sources/` | GLSL, scripts and builds of all SPIR-V headers except the SR4 kernels: `build.sh` (our own kernels) and `build_amd.sh` (the AMD-derived kernels; fetches AMD's FSR 4.1.2 Lite DLL, SDK v2.4.0, SHA-256 checked) |
| `vela_assets/fsr411` | the FSR 4.1.1 shader/initializer bundles the DLL embeds (Vela's modified passes) |
| `build/` | `dll_build_prv.sh` (the DLL build, runs in `ubuntu:24.04`), `prv_tools.py` (embed only `fsr411/`), `build_bench_prv.sh` (aarch64 test bench), `prv_overlay.py` (the exact edit that removed 4.0.2, as applied to the previous sources) |

The Vulkan provider samples 24-bit depth directly from the game's image when the driver
supports sampling that format and the bridge supplies its exact Vulkan format. For
depth/stencil images the sampled view covers only the depth aspect. The 32-bit float depth
and existing R32 color inputs retain their original format mapping. The bridge still
normalizes forward-Z inputs where required by FSR 4.

## Build

1. Install Docker. From this folder run `sh build.sh` (Linux, macOS or Git Bash on Windows; ~10 min, network needed).
2. The build log must end with `PASS: frozen inputs, AMD64 exports, asset identities and normal/debug modes`.
3. The original Vela 0.8.21 DLL has md5 `d230a1208c5ad78b6ea573536d41184f`. Source changes, including native
   depth support, change this checksum. The reproducible build pins the following inputs:
   - base image `ubuntu:24.04` with the MinGW packages pinned in `build/dll_build_prv.sh` (`g++-mingw-w64-x86-64-posix 13.2.0-6ubuntu1+26.1`,
     `binutils-mingw-w64-x86-64 2.41.90.20240122-1ubuntu1+11.4`; the versions are printed at the top of `out/build.log`);
   - Vulkan-Headers `v1.4.367`, checked against commit `9fbc2a782ee3f8a4db64e7d991e23da75e893f44`;
   - the linker image base is fixed to `0x250460000` (GNU ld otherwise picks a random base, which changes the checksum and every absolute address);
   - `SOURCE_DATE_EPOCH=1793577600`.
   A newer MinGW package in the Ubuntu archive than the pinned one makes the build stop at install time instead of giving a different DLL.
4. Optional checks of the generated kernels: `sh sr4-kernels/build.sh`, `sh spirv-sources/build.sh` and `sh spirv-sources/build_amd.sh` (each rebuilds its headers and compares them with `overlay/gen`, `overlay/ov` and `overlay/ov2`).
5. Compile and run [the CPU depth format test](build/depth-input-test.cpp) with a C++20 compiler and Vulkan headers.
   The test requires no Vulkan loader.

## FSR 4.1.2 Lite K2 performance experiment

This branch adapts the [color-tap reuse idea from FSR 4.1.2 Performance Overrides](https://github.com/zgauthier2000/fsr4-shader-performance-overrides/blob/6bb1ffe089705511ccc716991928754a21e0470d/docs/how-it-works.md) to Vela's native Vulkan Lite postpass. Vela's K2 already shares taps horizontally. The experiment also reuses the converted taps vertically when the rounded lower-row center is at the same X and advances by zero or one texel in Y. This reduces the two windows from 24 fetch-and-convert operations per invocation to 12 or 16 on the reuse path. Other coordinates use the original fetches. The experiment keeps the network weights and descriptor layout and uses no additional workgroup memory. The existing SR4 skipped-frame shader remains in its own pipeline.

Rebuild the provider with the [experimental SPIR-V header](spirv-sources/README.md#experimental-k2-color-tap-sharing). Select FSR 4.1.2 Lite and prepend `VELA_FSR412_K2_SHARED_TAPS=1` to that game's existing Steam launch options. The default and `0` select the stock shader. A rejected experimental pipeline falls back to the stock shader. The provider's diagnostic line reports `k2_shared_taps=1` only after the experimental pipeline was created.

For an isolated GPU comparison, use the provider-linked `dispatch-smoke` bench. Point `FSR4_VK_ASSET_ROOT` to the sidecar root if needed. Lite has embedded kernels and only requires the directory `fsr411/general` to satisfy the existing asset-root check in a non-embedded bench. Use distinct output paths for the two runs. The JSONL report contains a hash of each frame, GPU time for the whole Lite context and the K2 GPU time in `passes.k2`.

```bash
export FSR4_TEST_VERSION=4.1.2 FSR4_TEST_RENDER_SIZE=960x540 FSR4_TEST_OUTPUT_SIZE=1920x1080
export CP_VELA_DESC=0 FSR4_TEST_PROFILE_FRAMES=12
VELA_FSR412_K2_SHARED_TAPS=0 ./dispatch-smoke unused unused unused stock.rgba16f --provider-temporal
VELA_FSR412_K2_SHARED_TAPS=1 ./dispatch-smoke unused unused unused shared.rgba16f --provider-temporal
```

On Windows with an RTX 4060 and Vulkan 1.3, all 12 RGBA16F frame hashes matched in each of the two render-size comparisons. The first and last frame files also matched byte for byte. Timings below are short-run medians of the full GPU context, after dropping two frames from each run.

| Render → output | Stock | Shared taps |
| --- | ---: | ---: |
| 960×540 → 1920×1080 | 1.247 ms | 1.245 ms |
| 1280×720 → 1920×1080 | 1.281 ms | 1.359 ms |

The newer glslang 16.6/SPIRV-Tools 2026.4 build diverged from the stock output in the temporal test. The checked-in variant uses the tool versions that reproduce the stock shader. The Windows runs did not establish a speedup.

### Odin 3 result

The native AArch64 bench ran on armadaOS with Adreno 830 and Turnip Mesa 26.3.0, using Vulkan 1.3 and GPU-only Lite. At each render size it ran a 36-frame synthetic temporal sequence four times, alternating the stock and reuse pipelines in ABBA or BAAB order. After discarding the first six frames per run, each row has 60 timed samples per pipeline. The GPU clock read 660 MHz at the start and end of each run, and the sampled GPU temperature was 42.6–49.2 °C.

| Render → output | Stock K2 P50 / P95 | Reuse K2 P50 / P95 | Stock Lite context P50 / P95 | Reuse Lite context P50 / P95 |
| --- | ---: | ---: | ---: | ---: |
| 960×540 → 1920×1080 | 1.090 / 1.234 ms | 1.713 / 1.784 ms | 7.827 / 8.077 ms | 8.558 / 8.722 ms |
| 1280×720 → 1920×1080 | 1.082 / 1.134 ms | 1.748 / 1.786 ms | 7.828 / 7.941 ms | 8.524 / 8.607 ms |

All 36 frame hashes matched across the four runs at each resolution. The first and last RGBA16F frames also matched byte for byte. K2 took 0.622–0.665 ms longer and the full context took 8.9–9.3% longer at the median. Both repeat comparisons showed the same regression. Keep the stock K2 as default and retain the reuse path as an opt-in experiment on this branch.

The initial bench timed out because it hashed the whole mapped output again for its stdout log. The bench now uses the JSONL report's hash for both outputs, and the measured runs completed. These timings cover native Vulkan dispatch with synthetic textures. In-game frame rate, GPU load, HTP and the packaged provider were outside this run.
