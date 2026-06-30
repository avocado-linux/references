# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with NVIDIA GStreamer YOLO Object Detection

This guide walks you through building and running the YOLO object detection reference on Avocado OS. The app captures video from a USB camera on the Jetson Orin Nano, runs GPU-accelerated object detection, and serves the annotated feed as an MJPEG stream.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- An NVIDIA Jetson Orin board: **Orin Nano Developer Kit** (default) or **AGX Orin Developer Kit**
- USB (UVC) camera (e.g., Opal Tadpole)
- SD card or USB cable for flashing

To target the AGX Orin, pass `--target jetson-agx-orin-devkit` to the `avocado`
commands below. The committed TensorRT engine is built for the Orin Nano, so on
the AGX the on-device fallback compiles a matching engine on first boot (a
one-time, few-minute cost, then cached) — the dashboard comes up automatically
once it finishes.

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference nvidia-gstreamer-yolo nvidia-gstreamer-yolo
cd nvidia-gstreamer-yolo
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and resolves the runtime packages across the extensions. The dependency layer (`vision-runtime`) includes TensorRT (`python3-tensorrt`, `tensorrt-core`), the CUDA Python bindings (`python3-cuda`), cuDNN, OpenCV (used for image pre/post-processing only), the NVIDIA GStreamer plugins, the UVC camera driver, and Python + PyGObject + Flask — all from the feed, no vendored pip packages.

### Extension layout

The pipeline is split across four extensions so an OTA only re-ships what changed — see the README's [Extension layout](README.md#extension-layout) table. In short: `vision-runtime` (deps), `vision-models` (the ONNX), `vision-engines` (the prebuilt TensorRT engine), and `vision-app` (the code, plus its tunables in `app.service`).

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build composes each extension. Each one ships as a plain overlay — the YOLO11n model from `vision-models/overlay/usr/lib/app/models/`, the prebuilt TensorRT engine from `vision-engines/overlay/usr/lib/app/engines/`, and the application code from `vision-app/overlay/`. There is no pip/compile step — Flask and the rest come from the feed via `vision-runtime`.

## Deploy

Flash the image to an SD card or eMMC, connect a USB camera, and boot the Jetson Orin Nano.

```bash
avocado provision -r dev
```

## Verify

Log in as `root` with an empty password. The reference ships a **prebuilt FP16 TensorRT engine** (committed in the `vision-engines` overlay and shipped read-only to `/usr/lib/app/engines/`), so the app starts detecting immediately — no on-device compile wait.

`yolo-engine-build.service` still runs at boot but is a near-instant no-op while the prebuilt engine is present. It only compiles an engine when there isn't one for the active model — e.g. you swap to `yolo11s`, or the embedded engine fails to load after a TensorRT version bump in the feed (in which case the app rebuilds it on-device automatically, a one-time ~few-minute cost that's then cached under `/var/lib/app`).

Open your browser to `http://<device-ip>:5000` to view the dashboard.

```bash
systemctl status yolo-engine-build   # one-time engine compile (first boot)
systemctl status app
journalctl -u app -f
```

You should see output like:

```
app starting
  device: avocado-jetson-orin-nano-devkit
  camera: /dev/video0 (1280x720@30fps)
  model: /usr/lib/app/models/yolo11n.onnx
  tensorrt: 10.3.0
  loading TensorRT engine: /usr/lib/app/engines/yolo11n.onnx.fp16.engine
  TensorRT engine active (warmup: 42ms, in=(1, 3, 640, 640) out=(1, 84, 8400))
  detector ready — backend=TensorRT target=CUDA
  trying pipeline 1/4 [nvidia-mjpeg-decode]...
  pipeline started: [nvidia-mjpeg-decode] (GPU=True)
```

If TensorRT can't initialize for any reason, the app falls back to CPU inference via OpenCV DNN (`backend=OpenCV target=CPU` — much slower) so the dashboard still works.

The dashboard shows a live annotated video feed, detected objects with confidence scores, inference FPS, and device metrics.

### API Endpoints

- `GET /api/stats` — device metrics, model status, and current detections
- `GET /api/detections` — current detections only
- `GET /stream` — live MJPEG stream with bounding boxes
- `GET /` — web dashboard

## Customize

### Configure your camera

Check what your camera supports and adjust the settings:

```bash
v4l2-ctl --list-formats-ext -d /dev/video0
```

Uncomment and edit the camera tunables in `vision-app/overlay/usr/lib/systemd/system/app.service`:

```ini
Environment=CAMERA_DEVICE=/dev/video0
Environment=CAMERA_WIDTH=1280
Environment=CAMERA_HEIGHT=720
Environment=CAMERA_FRAMERATE=30
```

On-device you can `systemctl edit app` to drop in an override and `systemctl
restart app` for a quick test without rebuilding.

### Change the model

Replace `yolo11n.onnx` with a different YOLO11 variant for accuracy vs. speed:

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `yolo11n.onnx` | 11 MB | Fastest | Good |
| `yolo11s.onnx` | 37 MB | Fast | Better |
| `yolo11m.onnx` | 77 MB | Medium | High |

Export a new model to ONNX (TensorRT 10 handles recent opsets — opset 17 is a safe default):

```bash
uv run --with ultralytics python3 -c "
from ultralytics import YOLO
model = YOLO('yolo11s.pt')
model.export(format='onnx', opset=17)
"
cp yolo11s.onnx vision-models/overlay/usr/lib/app/models/
```

Point the app at the new file via a `MODEL_PATH` Environment line in `app.service` (or just replace `yolo11n.onnx`). The engine filename is derived from the model name, so a new model has no prebuilt engine and triggers a fresh on-device build automatically — or commit a prebuilt one into `vision-engines/overlay/usr/lib/app/engines/` to keep first boot instant (see [Regenerating the engine](#regenerating-the-engine)). To force a rebuild after re-exporting the *same* filename, delete the cached engine: `rm /var/lib/app/*.engine`.

### Adjust detection sensitivity

Uncomment `CONFIDENCE_THRESHOLD` / `NMS_THRESHOLD` in `app.service`:

```ini
Environment=CONFIDENCE_THRESHOLD=0.3    # lower = more detections (default 0.5)
Environment=NMS_THRESHOLD=0.45          # non-maximum suppression threshold
```

### Regenerating the engine

A TensorRT engine is GPU- and TRT-version-specific, so it's built on matching
hardware (the Orin Nano) and committed into the `vision-engines` overlay. To
regenerate it (after swapping the model, or on a TensorRT bump), let the device
build one and copy it back into the reference:

```bash
scp root@<device-ip>:/var/lib/app/<model>.onnx.fp16.engine \
    vision-engines/overlay/usr/lib/app/engines/
```

The next `avocado build` ships it directly via the overlay. If you skip this,
the on-device fallback still produces a working engine at first boot — it just
costs a few minutes once.

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
