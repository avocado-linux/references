# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with NVIDIA GStreamer YOLO Object Detection

This guide walks you through building and running the YOLO object detection reference on Avocado OS. The app captures video from a USB camera on the Jetson Orin Nano, runs GPU-accelerated object detection, and serves the annotated feed as an MJPEG stream.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- NVIDIA Jetson Orin Nano Developer Kit
- USB (UVC) camera (e.g., Opal Tadpole)
- SD card or USB cable for flashing

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

This pulls the SDK container image and installs `nativesdk-uv` for pip package compilation. Runtime packages include TensorRT (`python3-tensorrt`, `tensorrt-core`), the CUDA Python bindings (`python3-cuda`), cuDNN, OpenCV (used for image pre/post-processing only), GStreamer plugins, and the UVC camera driver.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which uses `uv pip install` to download Flask. The YOLO11n model (`yolo11n.onnx`) is already checked into the overlay at `app/overlay/usr/lib/app/models/`. Then `app-install.sh` copies the packages into the extension sysroot.

## Deploy

Flash the image to an SD card or eMMC, connect a USB camera, and boot the Jetson Orin Nano.

```bash
avocado provision -r dev
```

## Verify

Log in as `root` with an empty password. The reference ships a **prebuilt FP16 TensorRT engine** (`app/overlay/usr/lib/app/engines/yolo11n.onnx.fp16.engine`), so the app starts detecting immediately — no on-device compile wait.

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

Edit the environment variables in `app/overlay/usr/lib/systemd/system/app.service`:

```ini
Environment=CAMERA_DEVICE=/dev/video0
Environment=CAMERA_WIDTH=1280
Environment=CAMERA_HEIGHT=720
Environment=CAMERA_FRAMERATE=30
```

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
cp yolo11s.onnx app/overlay/usr/lib/app/models/
```

Point the app at the new file via the `MODEL_PATH` env var in `app.service` (or replace `yolo11n.onnx`). The engine filename is derived from the model name, so a new model triggers a fresh on-device engine build automatically. To force a rebuild after re-exporting the *same* filename, delete the cached engine: `rm /var/lib/app/*.engine`.

### Adjust detection sensitivity

Edit `app/overlay/usr/local/bin/app.py`:

```python
CONFIDENCE_THRESHOLD = 0.3    # lower = more detections (default 0.5)
NMS_THRESHOLD = 0.45          # non-maximum suppression threshold
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
