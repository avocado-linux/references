# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Python YOLO Object Detection

This guide walks you through building and running the Python YOLO Object Detection reference on Avocado OS. The app captures video from a USB webcam, runs YOLOv8n object detection on the CPU via OpenCV's DNN module, and serves the annotated feed as an MJPEG stream with a Flask dashboard. The same extension builds for every supported target — no GPU or vendor accelerators required.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A USB (UVC) webcam
- A supported target:
  - Raspberry Pi 5
  - NXP i.MX 8MP EVK, i.MX 91 FRDM, i.MX 93 EVK, or i.MX 93 FRDM
  - NVIDIA Jetson Orin Nano Developer Kit
- An SD card (Raspberry Pi / NXP) or a USB cable for flashing (Jetson). See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements.

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference python-yolo python-yolo
cd python-yolo
```

This reference defaults to `raspberrypi5`. To target other hardware instead, pass `--target`:

```bash
avocado init --reference python-yolo --target jetson-orin-nano-devkit python-yolo
cd python-yolo
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-uv` for pip package compilation. Runtime packages include OpenCV (CPU DNN), the GStreamer V4L2 and JPEG plugins, Python 3 with NumPy and the GObject bindings, the `uvcvideo` kernel module so most webcams Just Work, and `v4l-utils` for diagnostics.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which uses `uv pip install --target app/packages flask` to download Flask and its dependencies. The YOLOv8n model (`yolov8n-416.onnx`) is already checked into the overlay at `app/overlay/usr/lib/app/models/`. Then `app-install.sh` copies the pip packages and the model into the extension sysroot at `/usr/lib/app/`.

## Deploy

### SD card targets (Raspberry Pi 5, NXP i.MX)

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device, connect the USB webcam, and apply power.

### NVIDIA Jetson Orin Nano

```bash
avocado provision -r dev --profile tegraflash
```

Connect the USB webcam and follow the USB disconnect/reconnect prompts during the flash process.

## Verify

Log in as `root` with an empty password. The app service starts automatically on boot.

Open your browser to `http://<device-ip>:5000` to view the dashboard.

```bash
systemctl status app
journalctl -u app -f
```

You should see output like:

```
app starting on raspberrypi5
model: /usr/lib/app/models/yolov8n-416.onnx (input 416x416)
dashboard: http://0.0.0.0:5000
```

The dashboard shows a live annotated video feed with bounding boxes, an object counter overlay, and live inference FPS. The app tries an MJPEG capture pipeline first (higher FPS on most webcams) and falls back to raw YUV.

### API endpoints

- `GET /` — web dashboard
- `GET /stream` — live MJPEG stream with bounding boxes
- `GET /api/stats` — detections, inference FPS, and device info as JSON

## Customize

### Configure your camera

Check what your camera supports and adjust the settings:

```bash
v4l2-ctl --list-formats-ext -d /dev/video0
```

Uncomment and edit the environment variables in `app/overlay/usr/lib/systemd/system/app.service`:

```ini
Environment=CAMERA_DEVICE=/dev/video0
Environment=CAMERA_WIDTH=640
Environment=CAMERA_HEIGHT=480
Environment=CAMERA_FRAMERATE=30
```

### Change the model

`app/overlay/usr/lib/app/models/yolov8n-416.onnx` is a stock Ultralytics export. To regenerate it:

```bash
pip install ultralytics
yolo export model=yolov8n.pt format=onnx imgsz=416
mv yolov8n.onnx app/overlay/usr/lib/app/models/yolov8n-416.onnx
```

Drop the resulting file at the same path and rebuild.

### Adjust detection sensitivity

The detector reads its thresholds from the environment. Add them to `app.service`:

```ini
Environment=CONFIDENCE_THRESHOLD=0.35   # lower = more detections
Environment=NMS_THRESHOLD=0.45          # non-maximum suppression threshold
```

### Rebuild after changes

After any change, rebuild and reprovision using the same Deploy command for your target:

```bash
avocado build
avocado provision -r dev --profile sd        # or --profile tegraflash for Jetson
```
