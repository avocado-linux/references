# Getting Started with RZ/V2N DRP-AI3 YOLOv3 Object Detection

This guide walks through building and running the YOLOv3 object detection reference on the SolidRun RZ/V2N HummingBoard. The app pulls frames from a looping video file (default) or the IMX678 MIPI CSI-2 camera, runs YOLOv3 (Darknet/COCO) inference on the RZ/V2N's on-chip DRP-AI3 accelerator using Renesas's pre-compiled TVM bundle from the RZ/V2N AI SDK v6.30, and renders the annotated feed full-screen on Wayland/Weston.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- SolidRun RZ/V2N HummingBoard SoM
- HDMI display connected to the carrier
- microSD card or eMMC for boot media
- `curl` on the build host (used by `fetch-model.sh` and `fetch-video.sh`)

## Initialize

```bash
avocado init --reference rzv2n-drpai-yolo rzv2n-drpai-yolo
cd rzv2n-drpai-yolo
```

## Fetch the DRP-AI3 model bundle

```bash
./fetch-model.sh
```

Pulls Renesas's pre-compiled YOLOv3 bundle from [rzv_ai_sdk](https://github.com/renesas-rz/rzv_ai_sdk) v6.00 — the small graph metadata + DRP-AI/AI-MAC engine descriptors from the repo, and the multi-MB compiled `deploy.so` from the release asset. Lands at `app/overlay/usr/lib/rzv2n-drpai-yolo/model/yolov3/`. `.gitignore`d.

## Fetch the sample video

```bash
./fetch-video.sh
```

Default: a 15s / 8 MB / 1080p H.264 clip of a busy NYC sidewalk — pedestrians, UPS truck, yellow taxi. Multiple YOLO targets per frame, the kind of scene a battery-powered outdoor camera (Ring / Nest / Arlo) would capture. Pexels free-license.

To use a different clip:

```bash
VIDEO_URL=https://your.cdn/clip.mp4 ./fetch-video.sh
```

The script's comments list a couple of curated alternatives (front-door delivery, suburban approach). The fetched file lands at `app/overlay/usr/lib/rzv2n-drpai-yolo/sample.mp4` — `.gitignore`d.

## Install

```bash
avocado install -f
```

Pulls the SDK container image and resolves runtime dependencies — `lib-tvm` (DRP-AI3 inference runtime), `drpai` (UAPI header for `/dev/drpai0`), the Renesas memory manager userspace libraries, GStreamer with libav/qtdemux/h264parse for video decode + `waylandsink`, OpenCV, and Weston.

## Build

```bash
avocado build
```

`app-compile.sh` clones [rzv_drp-ai_tvm](https://github.com/renesas-rz/rzv_drp-ai_tvm) at `v2.5.1`, runs `setup/make_drp_env.sh` with `PRODUCT=V2N` to overlay Renesas's DRP-AI-patched TVM headers (`kDLDrpAi`), then cmake cross-compiles the YOLOv3 inference binary linking against the target's `libtvm_runtime.so`.

## Deploy

```bash
avocado provision -r dev --profile sd --env AVOCADO_SD_DEVICE=/dev/sdX
```

(Replace `/dev/sdX` with your SD card device. Use `--profile emmc` for eMMC.)

## Verify

Log in as `root` with an empty password. The app service starts automatically after Weston:

```bash
systemctl status rzv2n-drpai-yolo
journalctl -u rzv2n-drpai-yolo -f
```

Expected output:

```
rzv2n-drpai-yolo starting
  source: video file /usr/lib/rzv2n-drpai-yolo/sample.mp4
  model: /usr/lib/rzv2n-drpai-yolo/model/yolov3
  drp_start_addr: 0xd0000000
  model loaded — outputs=3
  pipelines running
  frames=150 inference_avg=78.4ms detections_last=2
```

The annotated video plays full-screen on the connected HDMI display, looping when it reaches end-of-file.

## Customize

### Use a different video

Edit `Environment=VIDEO_PATH=...` in `app/overlay/usr/lib/systemd/system/rzv2n-drpai-yolo.service`, or drop a new file at `/usr/lib/rzv2n-drpai-yolo/sample.mp4`. Any container/codec GStreamer's `decodebin` can handle works (MP4, MKV, AVI; H.264, H.265, VP9, etc.). Re-run `avocado build && avocado provision` after changing.

### Switch to the IMX678 camera (currently broken)

The camera path is wired but disabled by default because the SolidRun `rzg2l-cru` driver misreports its V4L2 format on RZ/V2N at 4K — frames decode as colored vertical stripes. To experiment anyway:

1. Empty `VIDEO_PATH` in the service (`Environment=VIDEO_PATH=`).
2. Enable the camera-init unit: `systemctl enable --now rzv2n-drpai-yolo-camera.service`.
3. The app falls into the `v4l2src` branch, capturing from `/dev/video0`.

A proper fix would either patch the kernel to truncate 12→8 bit correctly, or change main.cpp to read the buffer as 1920×2160 16-bit-BE Bayer and demosaic via `cv::cvtColor(..., COLOR_BayerBG2BGR)`.

### Adjust detection thresholds

```ini
Environment=CONFIDENCE_THRESHOLD=0.4
Environment=NMS_THRESHOLD=0.5
```

### Override the DRP-AI reserved-memory base

If the `drp_reserved` carveout in your DTSI sits elsewhere:

```ini
Environment=DRP_START_ADDR=0x90000000
```

### Rebuild after changes

```bash
avocado build
avocado provision -r dev --profile sd --env AVOCADO_SD_DEVICE=/dev/sdX
```
