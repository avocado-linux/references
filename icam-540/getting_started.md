# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with ICAM-540 Dev

This guide walks you through booting an Avocado OS development environment on the Advantech ICAM-540. The runtime comes pre-installed with the Basler Pylon camera SDK, GStreamer, OpenCV, and hardware debugging tools.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- Advantech ICAM-540
- SD card or USB cable for provisioning
- Basler industrial camera (GigE or USB3)

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference icam-540 icam-540
cd icam-540
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

## Build

Build the runtime image:

```bash
avocado build
```

There are no compile steps in this reference — the build assembles the runtime from pre-built packages and extensions.

## Deploy

Provision and flash the ICAM-540:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the ICAM-540 and apply power.

## Verify

Log in as `root` with an empty password. SSH access is enabled by default.

Verify the camera is detected:

```bash
# List USB devices
lsusb

# Check V4L2 devices
v4l2-ctl --list-devices

# Scan I2C buses
i2cdetect -l
```

Test a GStreamer pipeline with a Basler camera:

```bash
# Capture a single JPEG frame
gst-launch-1.0 pylonsrc num-buffers=1 ! jpegenc ! filesink location=/tmp/test.jpg

# Stream MJPEG over UDP
gst-launch-1.0 pylonsrc ! nvvidconv ! nvjpegenc ! multipartmux ! tcpserversink port=5000
```

Test OpenCV:

```bash
python3 -c "import cv2; print(cv2.getBuildInformation())"
```

## Customize

### Add packages

Edit `avocado.yaml` to add packages under the `app` extension:

```yaml
  app:
    version: 0.1.0
    packages:
      gst-plugin-pylon: '*'
      opencv: '*'
      python3-pygobject: '*'   # add GStreamer Python bindings
      cuda-cudart: '*'         # add CUDA runtime
```

### Add application code

Create an `app/` directory with source code, overlays, and build scripts following the pattern from other references (e.g., `python-gstreamer-yolo`).

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev --profile sd
```
