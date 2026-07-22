# Getting Started with ExecuTorch Semantic Segmentation

This guide walks you through building and running the ExecuTorch semantic
segmentation reference on Avocado OS. The app cross-compiles a C++ binary that
runs a DeepLabV3-MobileNetV3 model on a USB camera with the portable ExecuTorch
CPU runtime, and streams the colorized per-pixel mask to your browser.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

For hardware targets, you will also need:

- Your target device and any required accessories (SD card, USB cable, serial console adapter)
- A USB webcam (UVC)
- See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements

## Initialize

Initialize a new project from this reference:

```bash
avocado init --reference executorch-segmentation executorch-segmentation
cd executorch-segmentation
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference executorch-segmentation --target imx93-evk executorch-segmentation
cd executorch-segmentation
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs the C++ cross-compilation
toolchain (`avocado-sdk-toolchain`, `nativesdk-cmake`), the ExecuTorch runtime
development libraries (`executorch-dev`, `executorch-staticdev`), and OpenCV
(`opencv-dev`).

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which generates a
CMake toolchain file from the SDK environment and cross-compiles the runner,
linking the portable ExecuTorch runtime statically. No model export happens at
build time — the DeepLabV3 model ships as a pre-exported, portable
`app/models/segmentation.pte`, so the build is a fast C++ compile with no PyTorch
or pip involved. Then `app-install.sh` copies the binary to
`/usr/bin/executorch-segmentation` and the model into the extension sysroot.

## Provision

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB disconnect/reconnect prompts during the flash process.

### NXP i.MX 

#### SD card
Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

#### emmc
Make sure to properly set the boot switch for serial downloader mode when flashing emmc!

```bash
avocado provision -r dev --profile uuu-emmc
```


Connect the USB webcam to the board before boot (or restart the service after
plugging it in).

## Verify

Log in as `root` with an empty password. The `executorch-segmentation` service
starts automatically on boot.

Confirm the runtime and model load correctly — this needs no camera:

```bash
executorch-segmentation --selftest
```

You should see:

```
[selftest] output size = 1376256 (expected 1376256) PASS
```

Check the service and camera:

```bash
systemctl status executorch-segmentation
ls /dev/video0
```

Then open `http://<board-ip>:8080/` in a browser. You will see the live camera
feed with a colorized segmentation mask blended over it, plus the on-device
inference rate. Point the camera at people, chairs, bottles, or potted plants
(all PASCAL VOC classes).

Watch the logs:

```bash
journalctl -u executorch-segmentation -f
```

## Customize

### Trade speed for detail

Segmentation on a portable CPU is a few frames per second at 256×256 (fewer on
the Cortex-A55 boards, more on the Jetson). Lower `kInputSize` in
`app/src/main.cpp` for higher frame rates at a coarser mask — then update
`INPUT_SIZE` in `tools/export_model.py` and re-export the model to match.

### Adjust the overlay

Change the blend strength in the `cv::addWeighted(...)` call in
`app/src/main.cpp`.

### Use a different model

Edit `tools/export_model.py` and re-export (a one-time, offline step; see
`app/models/README.md`). Any torchvision segmentation model that lowers to
portable ExecuTorch operators works; keep the `(1,3,H,W) -> (1,21,H,W)` contract
or update `kNumClasses` and the color palette in `main.cpp`.

### Pick a camera

Set `CAMERA=/dev/videoN` in
`app/overlay/usr/lib/systemd/system/executorch-segmentation.service`.

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
