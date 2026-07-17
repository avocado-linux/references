# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Intel RealSense Web Visualizer

## Prerequisites

- [Avocado CLI](https://avocado.run) >= 0.41.0
- Docker or a compatible container runtime
- An Intel RealSense depth camera (D415, D435, D435i, D455, or L515) connected via USB
- A supported target device (Raspberry Pi 4/5, NVIDIA Jetson Orin Nano/AGX Orin, or NXP i.MX)

## Initialize

```bash
avocado init --reference realsense
cd realsense
```

## Install

```bash
avocado install -f
```

## Build

```bash
avocado build
```

This cross-compiles the C++ app inside the SDK container with CMake, linking the packaged `librealsense2`, `libmicrohttpd`, and `libjpeg-turbo` libraries from the target sysroot, then assembles the system extension with the compiled binary and those runtime libraries.

## Deploy

Provision the device for the first time by flashing media. Use the profile that matches your target:

### Raspberry Pi (SD card)

```bash
avocado provision -r dev --profile sd
```

### Raspberry Pi (USB flash)

```bash
avocado provision -r dev --profile usb
```

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

### NXP i.MX

```bash
avocado provision -r dev --profile sd
```

For subsequent updates during development, use `avocado deploy` to push changes over LAN without re-flashing.

## Verify

1. Plug the RealSense camera into a USB port on the target device.
2. Connect the device to your network (Ethernet or Wi-Fi).
3. Open a browser and navigate to `http://<device-ip>:5000`.

The dashboard displays three live feeds:

- **Color Stream** — standard RGB video
- **Depth Colormap** — depth data rendered as a jet heatmap
- **Infrared Stream** — raw IR camera view

Use the toggle buttons in the toolbar to show or hide individual panels. Click on any feed to measure the distance at that pixel — the measurement bar at the top shows the distance in centimeters/meters and the 3D coordinates relative to the camera.

To confirm the service is running, log in over SSH as `root` with an empty password and check its status:

```bash
ssh root@<device-ip>
systemctl status realsense-visualizer
```

You should see the service `active (running)`.

## Customize

The application source is `app/src/app.cpp`, built by `app/src/CMakeLists.txt`.

### Change the port

Edit the `kPort` constant near the top of `app/src/app.cpp`, then rebuild.

### Change resolution or frame rate

Adjust the `kWidth`, `kHeight`, and `kFps` constants in `app/src/app.cpp`. Note the comment about USB 2.0 bandwidth — three streams at 30 fps can exceed it.

### Add a dependency

Add the runtime package to the `app` extension's `packages` list in `avocado.yaml` and its `-dev` package to the SDK `compile.app.packages` list, then link it in `app/src/CMakeLists.txt`.
