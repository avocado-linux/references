# Getting Started with astra-1680-deepx

This guide takes you from zero to a running DeepX M1 NPU inference demo on a Grinn Astra SL1680 SBC.

## Prerequisites

- **Hardware:** Grinn Astra SL1680 SBC (`grinn-astra-1680-sbc`) with a DeepX M1 NPU on the PCIe bus, a display connected to HDMI, and a USB UVC camera for the Qt object-detection demo.
- **Media:** an SD card (or the board's supported boot media) for first-time provisioning.
- **Host:** the [Avocado CLI](https://docs.peridio.com) installed, plus Docker (the SDK runs in a container).
- **Network:** the board and host on the same network if you want to sideload iterative updates with `avocado deploy`.

## Initialize

Clone the references repo and enter the reference:

```bash
git clone https://github.com/avocado-linux/references.git
cd references/astra-1680-deepx
```

`default_target` is already set to `grinn-astra-1680-sbc`, so no `--target` flag is needed.

## Install

Resolve and fetch all extensions, packages, and SDK dependencies declared in `avocado.yaml`:

```bash
avocado install
```

## Build

```bash
# Base bring-up image (Weston desktop only):
avocado build -r dev

# Full DeepX stack (driver + runtime + models + Qt demo):
avocado build -r dev-deepx
```

For this reference the build step cross-compiles, inside the SDK against `grinn-astra-1680-sbc`:

- **`deepx-driver`** — the DeepX PCIe kernel modules (`dx_dma`, `dxrt_driver`), built against `kernel-devsrc`.
- **`deepx-rt`** — the DXRT C++ inference runtime and `dxrt.service`.
- **`deepx-models`** — sample ONNX/DX models, fetched and staged for the NPU.
- **`deepx-qt-example`** — the Qt5/QML YOLO detection app (built against Qt + OpenCV).

It then composes the extensions and builds the rootfs/initramfs images (with the `dev` permissions profile — empty root password, **not for production**).

## Deploy

**First time (provision the board):**

```bash
avocado provision -r dev-deepx
```

Follow the prompts to write the image to your boot media, then boot the board. Provisioning is a one-time step per device.

**Iterative updates (already provisioned + reachable on the network):**

```bash
avocado deploy -r dev-deepx -d <board-ip>
```

This sideloads only the changed extensions over SSH/HTTP — no reflash.

## Verify

After the board boots into the `dev-deepx` runtime:

```bash
# NPU kernel modules loaded:
lsmod | grep -E 'dx_dma|dxrt_driver'

# DXRT runtime service is active:
systemctl status dxrt.service
```

On the connected HDMI display, Weston starts in a kiosk session and the Qt YOLO demo (`qt-deepx-example.service`) draws bounding boxes over the live camera feed. Check the service if the window doesn't appear:

```bash
systemctl status qt-deepx-example.service
journalctl -u qt-deepx-example.service -f
```

## Customize

- **Models:** replace or add models in the `deepx-models` extension (`files/dx-models-*.sh`) to run your own network on the NPU.
- **Application:** the `deepx-qt-example` extension (and `files/dx-qt-example-*.sh`) is the day-to-day app to edit; swap in your own detection logic or UI. A headless inference suite is also available via the `deepx-app` extension.
- **Runtime selection:** use `-r dev` for a minimal display-only image during bring-up, or `-r dev-deepx` for the full NPU stack.
- **Display:** adjust the Weston kiosk behavior in `files/weston-kiosk.conf` / `files/weston-kiosk.ini`.
- **Permissions:** the `dev` permissions profile sets an empty root password for convenience. Define a real profile under `permissions:` and point `rootfs`/`initramfs` at it before any production use.
