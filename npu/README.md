# Vela NPU system part (package 14)

It lets Vela run FSR 4 and FSR 4 Fast on the Hexagon NPU of the Snapdragon 8 Gen 2 (SM8550, HTP v73) and, experimentally,
of the Snapdragon 8 Elite (SM8750, HTP v79: the AYN Odin 3 and other devices with this chip). Without it Vela runs them on the GPU. It is a system part, so installing it needs **sudo once** (your password).

## Install (Desktop mode → Konsole, game closed)

1. Run: `curl -fsSL https://github.com/zrprod9-cmyk/vela/releases/download/v0.8.21/install-vela-npu.sh | sudo sh`
   Nothing else to download: the image carries the Qualcomm QNN runtime; the installer reads 3 DSP files from your device.
2. It ends with `Vela NPU: OK - all NPU graphs checked work` or `Vela NPU: FAILED - <reason>`. Start the game again; the Vela
   panel shows "on the NPU".

Remove: `curl -fsSL https://github.com/zrprod9-cmyk/vela/releases/download/v0.8.21/uninstall-vela-npu.sh | sudo sh`

## Game resolutions on the NPU

Package 14 has FSR 4 networks for these output sizes: 1920x1080, 1600x900 and 1280x720, and the newer 1600x904, 1440x810, 1280x800,
1152x648 and 960x540. At any other size, FSR 4 runs on the GPU.

- On the Retroid Pocket 6, 960x540 has run on the NPU in a game (RE4). The other four new sizes pass the installer's fixed-input
  check on that device but have not been run in a game yet.
- On the Snapdragon 8 Elite the five new sizes are experimental: not tested there yet.
- 1366x768 is not supported on the NPU. The panel asks for 1920x1080.

## What it installs

| where | what | from |
|---|---|---|
| `/var/lib/extensions/armada-vela-npu.raw` | release asset `vela-npu-sysext-14.raw` (squashfs systemd system extension, sha256 `10acba9196a7a55f712d14451ed64a20385cc5eab045744be6a63dd264392ac1`, list in `vela-npu-sysext-14.contents.txt`) | `mk_public_sysext.sh`, byte-reproducible (built twice, same sha256) |
| inside: `/usr/lib64/vela-npu/fsr4npud`, `fsr4npu-check` | the NPU daemon (one process for all FSR 4 graphs) and its checker | ours, GPL-3.0-or-later; source and build steps: [`src/`](src/README.md) |
| inside: `/usr/lib64/vela-npu/nf4*.bin` (17) | the FSR 4.1.1 network compiled for HTP v73: 1920x1080 / 1600x900 / 1280x720 / 1600x904 / 1440x810 / 1280x800 / 1152x648 / 960x540 output × Performance / Ultra Performance, + exact | ours (from AMD's FSR 4 network) |
| inside: `/usr/lib64/vela-npu/v79/nf4*.bin` (17) | the same 17 graphs compiled for HTP v79 (SM8750), same file names | ours (from AMD's FSR 4 network) |
| inside: `/usr/lib64/vela-npu/v79/nf4*.bin` (17) | the same 17 graphs compiled for HTP v79 (SM8750), same file names | ours (from AMD's FSR 4 network) |
| inside: `cdsprpcd`, `libcdsprpc.so`, `libcdsp_default_listener.so` | the FastRPC client and the cDSP listener | quic/fastrpc a56e9d4, BSD-3-Clause |
| inside: `/usr/lib64/vela-npu/libQnnHtp.so`, `libQnnHtpV73Stub.so`, `libQnnSystem.so`; `/usr/lib/rfsa/adsp/libQnnHtpV73Skel.so`, `libQairtHtpV73Skel.so`, `libQnnHtpV73.so` | the Qualcomm AI Engine Direct (QNN) runtime 2.47.0.260601 (host part + HTP v73 part) | Qualcomm AI Engine Direct SDK runtime, unmodified, Qualcomm AI Stack License (sha256 of each file in `mk_public_sysext.sh`) |
| inside: `/usr/lib64/vela-npu/libQnnHtpV79Stub.so`; `/usr/lib/rfsa/adsp/libQnnHtpV79Skel.so`, `libQairtHtpV79Skel.so`, `libQnnHtpV79.so` | the same runtime's HTP v79 part (SM8750) | same |
| inside: `/usr/lib64/vela-npu/libQnnHtpV79Stub.so`; `/usr/lib/rfsa/adsp/libQnnHtpV79Skel.so`, `libQairtHtpV79Skel.so`, `libQnnHtpV79.so` | the same runtime's HTP v79 part (SM8750) | same |
| inside: `/usr/share/licenses/armada-vela-npu/Qualcomm-AI-Stack-LICENSE.pdf`, `QNN_NOTICE.txt` | Qualcomm's licence for that runtime (the SDK's `LICENSE.pdf`) and its third-party Notice File, both unchanged (sha256 in `mk_public_sysext.sh`) | Qualcomm AI Engine Direct SDK 2.47.0.260601 |
| inside: `vela-npu.service`, `vela-npu-listener.service`, `vela-npu-setup.service` (source: [`units/`](units/)) | the daemon runs as a dynamic user in group `render`, no capabilities, read-only system; the listener runs as root with 2 capabilities (it needs the root-only `/dev/fastrpc-cdsp-secure`) | ours |
| inside: `vela-npu-setup.service.d/50-vela-npu-chip.conf`, `vela-npu.service.d/50-vela-npu-chip.conf` (source: [`units/`](units/)) | chip selection: on `qcom,sm8550` nothing changes; on `qcom,sm8750` the setup unit links `/run/vela-npu/graphs` to `v79/` and each graph's v79 file is mounted read-only over its v73 path | ours |
| inside: `vela-npu-setup.service.d/50-vela-npu-chip.conf`, `vela-npu.service.d/50-vela-npu-chip.conf` (source: [`units/`](units/)) | chip selection: on `qcom,sm8550` nothing changes; on `qcom,sm8750` the setup unit links `/run/vela-npu/graphs` to `v79/` and each graph's v79 file is mounted read-only over its v73 path | ours |
| inside: `70-vela-npu.rules`, `modules-load.d/vela-npu.conf` | `/dev/fastrpc-cdsp` and `/dev/dma_heap/system` → group `render`, mode 0660: this is how the daemon reaches the NPU without root; loads `system_heap` | ours |
| `/var/lib/extensions/armada-vela-npu-qnn/` (root:root) | directory extension (name kept from the first installer): DSP shell `fastrpc_shell_unsigned_3`, `libc++.so.1`, `libc++abi.so.1` read from the device's own `dsp` partition | the device |
| `/etc/systemd/system/vela-npu-boot.service` | starts the NPU service `vela-npu.service` after the extension merge at every boot | written by the installer |

The numbers in the main README were measured with an earlier NPU package. Package 14 measured the same on the Retroid Pocket 6
in the games checked (Control 8.32 ms on the NPU). The extension says `ID=armada VERSION_ID=44`; after an armadaOS update with another VERSION_ID,
systemd-sysext stops loading it and the installer must be run again (it refuses other versions unless `--force`).

## Experimental FSR 4.1.2 Lite graph for Odin 3

[`tools/export_lite_qnn.py`](tools/export_lite_qnn.py) exports the AMD normal 1080p Lite network using the SHA-256-pinned
`provider/sr4-kernels/tools/weights.bin` initializer. It rebuilds the seven network dispatches between `pass0_post` and K1.
Vela still performs the prepass, K1 and K2 on the GPU. Ultra Performance with the alternate Lite model is outside this graph.

The native ABI is NHWC U8, with scale 1 and zero point 128. Input `x` has shape `[1,540,960,16]`.
Output `p3u_o` has shape `[1,270,480,64]` and contains the complete feature plane before pixel shuffle.
Output `p1f_o` has shape `[1,540,960,16]` and contains neutral U8 codes (128). This preserves the existing three-tensor
pack/unpack ABI and accumulates the final residual before rounding and saturation.

### Build

Export one ONNX model as a CPU integer reference and another with fixed encodings for the QAIRT importer. Use an isolated
Python environment with NumPy and ONNX. To make the HTP DLC, set up QAIRT 2.49.0.260730 and run the following commands from
the repository root with a new output directory or fresh output filenames.

```bash
python -B npu/tools/export_lite_qnn.py --weights provider/sr4-kernels/tools/weights.bin --output lite-oracle.onnx
python -B npu/tools/export_lite_qnn.py --weights provider/sr4-kernels/tools/weights.bin --output lite-import.onnx --qairt-encodings fixed.json
qairt-converter --input_network lite-import.onnx --output_path lite.dlc --target_backend HTP --quantization_overrides fixed.json \
  --source_model_input_layout x NCHW --desired_input_layout x NHWC \
  --source_model_output_layout p3u_o NCHW --desired_output_layout p3u_o NHWC \
  --source_model_output_layout p1f_o NCHW --desired_output_layout p1f_o NHWC
```

For Windows QAIRT, invoke the converter using the same Python interpreter on the SDK's
`bin/x86_64-windows-msvc/qairt-converter` script and add the SDK's `lib/python` to `PYTHONPATH`.
Check the DLC for 8-bit weights and activations and verify all three I/O encodings with `qairt-dlc-info -d`.
On Odin 3 generate the context from that DLC with the matching AArch64 `qnn-context-binary-generator`, HTP backend,
ModelDlc and HTP NetRun extension configured with `dsp_arch=v79`, `soc_id=69` and an unsigned PD session.
The installed QAIRT 2.47 daemon rejected the newer context, so tests used a private daemon built against QAIRT 2.49 and
a separate socket selected with `VELA_NPUD_NAME`.

### Validation

The CPU integer reference matched all 8,294,400 final network feature codes captured from Vela's native Vulkan Lite path
on Odin 3 for the same input. The compiled W8A8 DLC ran on HTP v79. At the first convolution its 32,131 differing codes
were all half-way cases and matched round-half-up exactly. The original Vulkan path uses round-to-nearest-even.
The final HTP feature plane differed by a mean absolute 1.653 codes and up to 19 codes relative to the captured GPU reference.

At 960×540 → 1920×1080, each path ran the same 48-frame synthetic sequence twice. The Vulkan context measurements
exclude the first eight submissions of each run. The stock 4.1.1 path used the installed QAIRT 2.47 service and
`nf4_k1h`. Lite used the private QAIRT 2.49 service. The tested asynchronous Lite path outputs the preceding frame.

| Path | HTP execution P50 in the two runs | Vulkan context P50 / P95 |
| --- | ---: | ---: |
| Stock Vela 4.1.1 + NPU | 3.630 / 3.633 ms | 4.105 / 4.158 ms |
| 4.1.2 Lite GPU | — | 7.761 / 8.017 ms |
| 4.1.2 Lite + synchronous NPU | 3.155 / 3.207 ms | 10.817 / 10.831 ms |
| 4.1.2 Lite + asynchronous NPU | 3.250 / 3.225 ms | 4.665 / 4.676 ms |

Both Lite NPU modes completed 94 HTP jobs without errors or timeouts. The final RGB frame of the first asynchronous run
had a mean absolute difference of 0.00102 versus the time-aligned GPU frame, with a maximum of 0.294, on this synthetic SDR sequence.

### In-game validation on Odin 3

On 2026-11-20, FSR 4.1.2 Lite rendered the town scene in Trails in the Sky 1st Chapter
(Steam AppID `3447040`, build `26289760`) using the Hexagon NPU on an AYN Odin 3 running armadaOS.
The game-local DX11-to-DX12 bridge was rebuilt to accept `Fsr4Lite` on the existing game-specific path.
The Lite run used `model=fsr4lite`, `lossy=1`, `npu=2`, and a private QAIRT 2.49 daemon running the W8A8
`lite_fixed_float` graph on HTP v79. Stock Vela used its installed QAIRT 2.47 daemon and 4.1.1 graph.
This is an opt-in setup with a separately built v79 context. The standard NPU installer described above provides the stock path.

All four samples used the same town save and fixed camera, 1129×635 render resolution, 1920×1080 SDR output,
and frame generation disabled. Each measured window lasted about 20 seconds. Loading samples were excluded.
HTP execution P50 comes from the full daemon session, including warm-up.

| Path and run | Avg. FPS | Frame time P50 / P99 | Avg. GPU load | Avg. CPU load | HTP exec. P50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock 4.1.1, first run | 53.7 | 18.43 / 22.00 ms | 95.8% | 37.5% | 4.657 ms |
| 4.1.2 Lite, first run | 52.6 | 18.75 / 25.42 ms | 94.3% | 41.1% | 3.652 ms |
| Stock 4.1.1, matched repeat | 54.2 | 18.31 / 23.21 ms | 96.7% | 34.0% | 4.599 ms |
| 4.1.2 Lite, matched repeat | 54.6 | 18.24 / 20.82 ms | 97.2% | 31.8% | 3.705 ms |

Lite completed 6,381 HTP jobs across the two valid sessions with zero daemon errors and zero fallbacks in the
recorded provider counters. HTP execution time fell by about 19% in the matched repeat, while FPS and GPU load were
similar. GPU frequency held at 1100 MHz across the four samples. GPU temperature peaked at 103°C in the first Lite run.
The test covered one stationary scene. It did not measure NPU utilization, power, latency, or image quality in motion.

## Security
- Library search paths: only `/usr/lib64/vela-npu` (`fsr4npud` RPATH, `libcdsp_default_listener` RUNPATH), plus `$ORIGIN`
  on the three unmodified Qualcomm host libraries, which resolves to the same root-owned, read-only folder. The builder
  fails on any search path outside `/usr/lib64/vela-npu` and on any home or `/tmp` path string (the Qualcomm runtime's mkstemp template `/tmp/tmp.XXXXXX` excepted; the daemon runs with `PrivateTmp=yes`).
- All files root:root, no setuid/setgid, nothing group- or world-writable (checked by the builder).
- Device access: `/dev/fastrpc-cdsp` and `/dev/dma_heap/system` get group `render`, mode 0660. On armadaOS the default user
  is in `render`, so the user's own programs can open them too (not only the daemon); `/dev/fastrpc-cdsp-secure` (the
  root PD) stays root-only.

## Qualcomm runtime: conditions
- The 10 Qualcomm files are distributed only inside this image (and the armadaOS `vela-npu` package made from it), as part
  of Vela. They are never offered as separate downloads: the Qualcomm AI Stack License allows distribution "as incorporated
  in Your software application", not on a standalone basis (section 1).
- They are unmodified (no strip, no patchelf); the licence and the Notice File ship next to them, unchanged.
- Export control: see section 10(f) of `Qualcomm-AI-Stack-LICENSE.pdf`.
- Building `fsr4npud` (`src/build.sh`) needs the Qualcomm AI Engine Direct SDK (QAIRT 2.47.0.260601) headers: get the SDK from Qualcomm
  (https://softwarecenter.qualcomm.com; exact download in `src/README.md`); no SDK header is in this repository.
- `fsr4npud` is GPL-3.0-or-later with a GPL-3.0 section 7 additional permission to link with and load the Qualcomm runtime
  (`LICENSING.md`).
- The source of `fsr4npud` and `fsr4npu-check` is in [`src/`](src/README.md) (file table, licences, build steps, and how the image's
  binaries relate to it).
