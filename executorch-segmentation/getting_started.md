# Getting Started with executorch-segmentation

Go from zero to a board running live semantic segmentation on the portable
ExecuTorch CPU runtime, streamed to your browser.

## Prerequisites

- **Avocado CLI** `>= 0.26.0` and Docker (the SDK runs in a container).
- **A supported board:** `jetson-orin-nano-devkit`, `imx8mp-evk`, or `imx93-evk`.
- **A USB webcam** (UVC).
- Network reachability to the board (the dashboard is served over HTTP).

No PyTorch or pip is involved in the build — the model ships pre-exported.

## Initialize

```sh
git clone https://github.com/avocado-linux/references.git
cd references/executorch-segmentation
export AVOCADO_TARGET=jetson-orin-nano-devkit   # or imx8mp-evk / imx93-evk
```

The committed `app/models/segmentation.pte` is the DeepLabV3-MobileNetV3 model,
already lowered to portable ExecuTorch. (To regenerate or swap it, see
`app/models/README.md` — a one-time offline step, not part of the build.)

## Install

```sh
avocado install
```

Pulls the prebuilt feed packages: the ExecuTorch runtime dev/static libs
(`executorch-dev`, `executorch-staticdev`), `opencv` + `opencv-dev`, the camera
module, and the SDK toolchain + CMake. All binary — nothing is compiled here.

## Build

```sh
avocado build
```

This is a **fast C++ cross-compile** (typically seconds): CMake links the runner
against the ExecuTorch portable runtime (statically) and OpenCV from the target
sysroot. There is no model export, no pip, and no network access at build time.

> **First-build things to verify.** This links a newer part of the feed than most
> references. If the build stops:
> - **ExecuTorch CMake targets / `executorch_target_link_options_shared_lib`** in
>   `app/src/CMakeLists.txt` — reconcile against the config `executorch-dev`
>   installs at `$OECORE_TARGET_SYSROOT/usr/lib/cmake/ExecuTorch/`. The
>   whole-archive wrap on `portable_ops_lib` is required, or `forward()` fails at
>   runtime with "operator not found".
> - The reference links only what the portable-only `executorch` package builds
>   (`executorch`, `extension_module`, `extension_data_loader`,
>   `extension_flat_tensor`, `portable_ops`) — no recipe changes needed.

## Deploy

```sh
avocado provision -r dev      # then flash per your board (SD / eMMC / NVMe)
```

- **Jetson Orin Nano:** flash to NVMe/SD per the board guide, then boot.
- **i.MX8MP / i.MX93 EVK:** flash eMMC/SD per the board guide, then boot.

`executorch-segmentation.service` starts on boot.

## Verify

**1. Prove the runtime** (no camera needed) over SSH:

```sh
executorch-segmentation --selftest
# [selftest] output size = 1376256 (expected 1376256) PASS   # 21*256*256
```

**2. Confirm the camera:**

```sh
ls /dev/video0
```

**3. Open the dashboard** at `http://<board-ip>:8080/` — you'll see the live
camera with a colorized segmentation mask blended over it, and the on-device FPS.
Point it at a person, chair, bottle, potted plant, etc. (the PASCAL VOC classes).

```sh
journalctl -fu executorch-segmentation
```

## Customize

- **Speed vs. detail:** lower `kInputSize` in `app/src/main.cpp` (and `INPUT_SIZE`
  in `tools/export_model.py`, then re-export) for higher FPS at coarser masks.
  Segmentation on a portable CPU is a few FPS at 256² — expect fewer on the
  Cortex-A55 boards, more on the Jetson.
- **Blend strength:** the `cv::addWeighted(...)` call in `main.cpp`.
- **Different model:** edit `tools/export_model.py` — any torchvision segmentation
  model that lowers to portable ops works; keep the `(1,3,H,W) -> (1,21,H,W)`
  contract (or update `kNumClasses` + the palette).
- **Pick a camera:** set `CAMERA=/dev/videoN` in the systemd unit.
