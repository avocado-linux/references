# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with NVIDIA DeepStream

Run DeepStream 7.1 natively on a Jetson Orin Nano (or AGX Orin) — no containers. A USB camera is fed through a GStreamer pipeline that detects people with PeopleNet, tracks them across frames with NvDCF, runs MoveNet (secondary GIE) to extract a 17-point COCO skeleton per person, runs YOLOX-Body-Head-Hand (second primary GIE) on the full frame to find hands, runs MediaPipe Hand Landmark (tertiary GIE) on each hand crop to regress 21 finger keypoints, and applies `nvdsanalytics` for ROI entry counters and dwell-time tracking. Bounding boxes, skeletons, hand keypoints, and zone overlays are rasterised by `nvdsosd` directly into the JPEG stream; the dashboard at `:8080` serves the resulting MJPEG plus a JSON stats endpoint.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+) on the build machine
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or a working local Docker daemon (the Avocado SDK runs in a container)
- The latest [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A Jetson Orin Nano DevKit or Jetson AGX Orin DevKit
- A USB C cable
- A UART to USB adapter
- A USB camera (UVC-compatible MJPEG, e.g. Logitech C920 / C270)
- A network-reachable path from a viewing machine to the device
- Internet access on the build machine — `app-compile.sh` downloads four models on the first build (PeopleNet from NGC; MoveNet, YOLOX-Body-Head-Hand, and MediaPipe Hand Landmark from PINTO mirrors; ~270 MB the first time, then cached)

## Initialize

```bash
avocado init --reference nvidia-deepstream nvidia-deepstream
cd nvidia-deepstream
```

To target Jetson AGX Orin instead of Orin Nano:

```bash
avocado init --reference nvidia-deepstream --target jetson-agx-orin-devkit nvidia-deepstream
cd nvidia-deepstream
```

## Install

```bash
avocado install -f
```

Downloads the Avocado SDK container and the runtime extensions declared in `avocado.yaml` (DeepStream 7.1, TensorRT, CUDA, cuDNN, the GStreamer NVIDIA plugins, Python).

## Build

```bash
avocado build
```

`app-compile.sh` runs first inside the SDK and stages four ONNX models into `app/overlay/usr/lib/nvidia-deepstream/models/`:

1. **PeopleNet** ONNX + labels from NGC (Person/Bag/Face detector). Used as the primary GIE.
2. **MoveNet** (single-pose Lightning) from PINTO's ONNX zoo — extract just `model_float32.onnx` and rewrite its input layer from NHWC to NCHW (a small `onnx.helper` Transpose insertion) so DS 7.1's `nvinfer` reads it cleanly. Used as secondary GIE on each Person crop for the 17-point body skeleton.
3. **YOLOX-Body-Head-Hand (320×320, non-post variant)** from PINTO — used as a second primary GIE on the full camera frame to find hands. The Python pad probe decodes the raw head output (grid + log-space + sigmoid) and applies per-class NMS in app.py.
4. **MediaPipe Hand Landmark sparse (224×224)** from PINTO's `hand_landmark` GitHub release — used as tertiary GIE on each detected hand crop to produce 21 finger keypoints + handedness + presence score.

`app-install.sh` then stages those into the sysroot. `avocado build` finishes by assembling the runtime extensions. Flask, PyGObject, and the rest of the Python runtime come from the Avocado package feed (`python3-flask`, `python3-pygobject`) — no pip install step is involved.

## Deploy

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB recovery-mode prompts. Plug in your USB camera before or after boot.

## First boot — engines

The reference ships **pre-built TensorRT FP16 `.engine` files** for the supported targets under `prebuilt-engines/<target>/<model>/`. `app-compile.sh` stages the engines for the current build target into `app/overlay/usr/lib/nvidia-deepstream/models/<model>/` and `app-install.sh` packages them into the sysext. At service start the preflight script copies each engine from the read-only `/usr/lib/...` location to the writable `/var/lib/...` location next to the ONNX, then nvinfer mmaps the engine and the pipeline reaches PLAYING in ~10–15 s. **No 12-minute first-boot compile** in the common case.

If the sysext doesn't ship an engine for a model — e.g. a different target with no committed engines yet, or a custom model swap — the fallback is to compile from the ONNX on first boot. Wait times in that fallback:

| Model | First-boot fallback build | Notes |
| --- | --- | --- |
| PeopleNet | ~30–60 s | Small ResNet34, FP16 build |
| MoveNet | ~2 min | TF Hub export; small but FP16 tactic search is real |
| MediaPipe Hand Landmark | ~60 s | Sparse 224×224 |
| YOLOX-BHH | ~6–7 min | FP16 tactic search across three FPN heads — the long pole |

### Why per-target engines?

TensorRT engines are pinned to GPU compute capability (sm_87 for both Orin Nano and AGX Orin) **and** the device's SM count, memory hierarchy, and TRT/CUDA version. Engines built for an Orin Nano won't necessarily run optimally (or at all) on an AGX Orin. The directory layout reflects that:

```
prebuilt-engines/
├── jetson-orin-nano-devkit/{peoplenet,movenet,handdet,handlandmark}/*.engine
└── jetson-agx-orin-devkit/{...}/*.engine     # populate from an AGX Orin
```

To regenerate or refresh engines (e.g. after a JetPack bump that invalidates the cache):

1. SSH to a device running the target hardware + the matching JetPack/TRT version.
2. Let the app run once so nvinfer compiles fresh engines under `/var/lib/nvidia-deepstream/models/<model>/*.engine`.
3. `scp` them back to the host under the right `prebuilt-engines/<target>/<model>/` directory and commit.
4. Next `avocado build` picks them up; next `avocado runtime deploy` ships them OTA.

### OTA-bumping engines

The preflight script size-compares the sysext-shipped engine against the cached `/var` copy on every boot. If they differ (post-OTA), the new engine overwrites the cached one and nvinfer loads the new engine on this boot. The cached `/var` engine is **not** authoritative across OTAs — the sysext is.

### Provision vs deploy

A full `avocado provision` (tegraflash reflash) wipes `/var` and copies engines fresh on first boot from `/usr/lib/...` to `/var/lib/...`. An `avocado runtime deploy` only swaps the sysext/confext A/B partitions; on the next boot the preflight detects the new engine in the swapped sysext and refreshes `/var`. Either way the device is up in seconds.

Flask doesn't bind port 8080 until `_start_pipeline()` returns, which waits for all four GIEs' engines to be loaded. If `http://<device-ip>:8080` is unreachable on first boot, check `journalctl -u app -f` to see which engine nvinfer is on.

## Verify

SSH into the device. The default `config` extension sets an empty root password for development:

```bash
ssh root@<device-ip>
```

### Service is running

```bash
systemctl status app
```

`Active: active (running)`.

### Pipeline produced frames

```bash
journalctl -u app -b --no-pager | tail -30
```

Look for `setting pipeline to PLAYING` and (after the engine build) `dashboard: http://0.0.0.0:8080`.

### Dashboard + live MJPEG stream

From any machine on the same network:

- Browser: `http://<device-ip>:8080` — live video with bounding boxes + per-object tracker IDs, plus an FPS / detection / track stats panel.
- Raw stream: `http://<device-ip>:8080/stream`
- JSON: `curl http://<device-ip>:8080/api/stats | jq`

Expected on Orin Nano at 720p: ~15–25 fps end-to-end with 1–2 people in frame. AGX Orin pushes 30+ fps comfortably.

### Track IDs persist across frames

Walk in and out of the frame; you should see the tracker assign a unique `id` per person (e.g. `id 1`, `id 2`) and keep it stable while the person stays visible. `unique_tracks` in the stats panel monotonically increases each time a new person enters.

## Customize

### Adapting to your camera

The defaults assume a UVC USB webcam that can stream **MJPEG at 1280×720, 30 fps**. If your camera is different, the workflow is:

**1. See what your camera can actually do.** SSH in and ask v4l2:

```bash
v4l2-ctl --list-devices
v4l2-ctl --device /dev/video0 --list-formats-ext
```

The first command shows which `/dev/video*` node your camera is on. The second prints every pixel format / resolution / framerate the camera supports. Look for an `MJPG` entry at the resolution and framerate you want.

**2. Override the defaults with a systemd drop-in.** No rebuild — write the file once on the device and `systemctl restart app`:

```bash
systemctl edit app
```

```ini
[Service]
Environment=CAMERA_DEVICE=/dev/video1
Environment=CAMERA_WIDTH=640
Environment=CAMERA_HEIGHT=480
Environment=CAMERA_FRAMERATE=30
```

The app reads these on startup and rebuilds the pipeline string with the new values — no other edits needed.

**3. If your camera doesn't list `MJPG`** (some webcams only do `YUYV`), the default pipeline can't negotiate. The fix is to change `_build_pipeline()` in `app.py` from the JPEG path:

```python
f"! image/jpeg,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
f"! jpegdec "
f"! videoconvert "
```

to a raw path:

```python
f"! video/x-raw,format=YUY2,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
f"! videoconvert "
```

(GStreamer calls YUYV `YUY2`.) Rebuild + redeploy.

**4. If you change the resolution, rescale the Center zone.** The ROI polygon in `analytics_config.txt` is in pixel coordinates of the configured frame. The defaults (`400;180;880;180;880;540;400;540`) are for 1280×720; at 640×480 the rectangle ends up mostly off-screen. Edit those four corner points in `app/overlay/etc/nvidia-deepstream/analytics_config.txt` to whatever you want, then rebuild + redeploy. A simple starting point is a centered rectangle covering roughly the middle 50% of the frame.

**5. Other camera sources.** This reference uses `v4l2src` for USB UVC cameras. For a Jetson **CSI** camera, swap `v4l2src` for `nvarguscamerasrc` and adjust the caps (CSI cameras typically expose `video/x-raw(memory:NVMM),format=NV12` directly, so the `jpegdec` and first `videoconvert` aren't needed). For an **RTSP / IP** camera, use `rtspsrc location=rtsp://… ! rtph264depay ! h264parse ! nvv4l2decoder`. Everything downstream of `nvstreammux` is the same regardless of source.

### Swap the detection model

PeopleNet detects person/bag/face. Other DeepStream-compatible TAO models that drop in with minimal config changes:

- **TrafficCamNet** (4-class: car/person/bicycle/roadsign) — included with DeepStream's `samples` package
- **DashCamNet** (4-class, dashcam-tuned)
- **YOLOv8** ONNX exports — needs a custom output parser

Edit `config_infer_peoplenet.txt` to point at the new ONNX + label file and rebuild.

### Add a secondary classifier

DeepStream's secondary GIE pattern lets you chain models — e.g., PeopleNet detects people, then a secondary model classifies each person's action / pose / clothing. Add another `nvinfer` element after the tracker with `process-mode=2`. See NVIDIA's `deepstream_test2_app_config.txt` for the canonical example. This reference already uses the pattern: MoveNet runs as a secondary GIE on each PeopleNet person bbox; see *Pose tracking* below.

### Pose tracking

MoveNet (Google, single-pose Lightning variant; ONNX from PINTO's pre-converted model zoo) runs as a **secondary GIE** with `gie-unique-id=2`, `process-mode=2`, `operate-on-gie-id=1`, `operate-on-class-ids=0` — so it only fires on the Person crops PeopleNet produces. Its output tensor (`[1, 1, 17, 3]` — `(y_norm, x_norm, confidence)` per COCO keypoint) is delivered as `NvDsInferTensorMeta` on each object meta (because `output-tensor-meta=1` is set and `network-type=100` disables nvinfer's built-in post-processing).

The pad probe reads each tensor via `tensor_meta.out_buf_ptrs_host` (the canonical pyds path — a `void**` `PyCapsule` that we walk with `ctypes`), drops any keypoint below `KEYPOINT_CONFIDENCE = 0.30` (set in `app.py`), projects the survivors back into image-pixel coordinates using the bbox, and attaches an `NvDsDisplayMeta` containing the joint circles + bone lines. `nvdsosd` rasterises that display meta into the same frame it paints the bbox onto, before `nvjpegenc` encodes the JPEG — so the skeleton arrives at the dashboard at the full pipeline frame rate inside the MJPEG stream itself, with no client-side rendering.

Knobs you'll likely touch:

- **`KEYPOINT_CONFIDENCE`** (in `app.py`) — raises/lowers the per-keypoint threshold. Lower values draw more joints but with more jitter on far-away or partially occluded people.
- **`input-object-min-width` / `input-object-min-height`** (in `config_infer_movenet.txt`) — drops MoveNet entirely on small detections. The defaults (`64 / 128`) keep the secondary inference off of distant or barely-visible people.
- **`interval`** (in `config_infer_movenet.txt`) — set to `1` or `2` to skip frames between pose inferences on the same tracker ID if the secondary GIE is dragging the overall framerate down on busy scenes. The tracker carries the ID across the skipped frames, so the skeleton just lags a beat behind the bbox.
- **`ENABLE_POSE=0`** (systemd drop-in) — drops the MoveNet secondary GIE from the pipeline entirely for benchmarking the detection/tracker pipeline alone.
- **`ENABLE_HANDS=0`** (systemd drop-in) — drops the YOLOX hand-detector and MediaPipe hand-landmark GIEs entirely; useful for benchmarking, or when you only care about bodies and skeletons.
- **Toggle at runtime**: the skeleton, hand, and zone overlays all default to **off**. The dashboard's *Show skeletons* button `POST`s to `/api/toggle/skeletons` (and *Show hands* / *Show zones* to `/api/toggle/hands` and `/api/toggle/zones`), flipping a server-side flag the pad probe consults each frame. No service restart required; the current state is reported in `/api/stats` under `pose.overlay_enabled`.

Swap MoveNet for a different pose model by replacing `app/overlay/usr/lib/nvidia-deepstream/models/movenet/movenet_singlepose_lightning.onnx` with another single-person top-down ONNX (any model that emits `[1, 1, N, 3]` keypoint outputs in normalised coords) and updating `KEYPOINT_NAMES` + `SKELETON_EDGES` to match. For multi-person bottom-up models (e.g., BodyPoseNet), you'd swap the primary GIE *and* add heatmap/PAF parsing — that's a separate reference rather than a config change.

### Output RTSP instead of MJPEG

DeepStream-idiomatic. Replace the appsink branch in `_build_pipeline()` with:

```
! nvvideoconvert ! nvv4l2h264enc ! h264parse ! rtspclientsink location=rtsp://...
```

…or use `gst-rtsp-server` to host the stream on the device. The Flask MJPEG approach in v1 is for "open it in a browser" simplicity.

### Adjust tracker behavior

`/etc/nvidia-deepstream/tracker_NvDCF.yml` is the NvDCF perf config — biased toward speed over IoU accuracy. For more aggressive ID persistence, switch to NVIDIA's `config_tracker_NvDCF_accuracy.yml` (shipped under DeepStream's samples directory). For the lightest tracker (IoU only, no visual features), use `config_tracker_IOU.yml`.

### Configure analytics zones

`nvdsanalytics` runs after the tracker and turns detections into operational metrics — without any extra inference. The shipped config (`/etc/nvidia-deepstream/analytics_config.txt`) defines:

- **Line crossing — `Entry`**: a vertical line through the center of a 1280×720 frame; people crossing left-to-right are counted as `Entry`, right-to-left in the reverse direction. Format: `line-crossing-<Name>=lx1;ly1;lx2;ly2;dx1;dy1;dx2;dy2` (line endpoints, then a direction-of-entry segment). **Ships disabled (`enable=0`)** — a single line is noisy with a head-on webcam, so `line_crossings` stays empty until you set `enable=1` on the `[line-crossing-stream-0]` block. The ROI dwell tracking below is what's on by default.
- **ROI — `Center`**: a centered rectangle covering roughly the middle ~50% of the frame. Any tracked person inside the polygon shows up in the buffer's `NvDsAnalyticsObjMeta` for that frame; `app.py` maintains per-tracker dwell timers on top of that membership signal.
- **Disabled examples** for `overcrowding` and `direction` filters — uncomment + edit to enable.

The results are surfaced two ways:

- **Painted onto the live MJPEG** by `app.py`: when the dashboard's *Show zones* button is on, the pad probe attaches an `NvDsDisplayMeta` for each ROI/line and `nvdsosd` rasterises it onto the video. `nvdsanalytics` itself runs with `osd-mode=0` and paints nothing — the overlay is driven by the app, defaults to off, and is toggled at runtime via `/api/toggle/zones` (no restart).
- **Exposed in `/api/stats`** under `analytics`:

  ```json
  "analytics": {
    "line_crossings": {"Entry": 42},
    "line_crossings_last_frame": {"Entry": 1},
    "rois": {
      "Center": {
        "current": [{"tracker_id": 17, "elapsed_seconds": 8.2}],
        "current_count": 1,
        "total_entries": 27,
        "completed_count": 12,
        "avg_dwell_seconds": 7.4,
        "max_dwell_seconds": 23.6,
        "recent_completed": [{"tracker_id": 16, "duration_seconds": 14.5}, ...]
      }
    }
  }
  ```

Coordinates in the config are in the pipeline's frame space (1280×720 by default). If you override `CAMERA_WIDTH` / `CAMERA_HEIGHT` via a systemd drop-in, rewrite the coordinates accordingly (or rescale linearly).

#### Add a new line or ROI

Edit `app/overlay/etc/nvidia-deepstream/analytics_config.txt` (in the reference repo, not on the device — it's a read-only confext at runtime), increment the stream-suffix block if you want a second line on the same stream, or duplicate the `[line-crossing-stream-0]` / `[roi-filtering-stream-0]` sections under fresh names. After rebuild + redeploy, both the painted overlay and the JSON endpoint will pick up the new zones automatically — `app.py` reads zone names from the metadata at runtime, it doesn't hardcode them.

### Rebuild after changes

After editing `app.py`, the nvinfer config, or the tracker config:

```bash
avocado build
avocado runtime deploy dev --device root@<device-ip>
```

`avocado deploy` streams just the changed sysext bytes; no re-flash.

For changes to `avocado.yaml` (new packages, new extensions), or for first-time deploy:

```bash
avocado build
avocado provision -r dev --profile tegraflash
```

## How the pipeline works

```
v4l2src ─► [MJPEG decode] ─► videoconvert ─► nvvideoconvert (NV12 NVMM) ─►
nvstreammux ─► nvinfer/primary (PeopleNet) ─► nvtracker (NvDCF) ─►
nvdsanalytics (ROIs) ─► nvinfer/secondary (MoveNet) ─►
nvinfer/secondary (YOLOX-Hand) ─► nvinfer/tertiary (MediaPipe Hand Landmark) ─►
nvvideoconvert ─► nvdsosd ─► nvjpegenc ─► appsink → MJPEG/Flask
```

(The two hand GIEs are dropped from the pipeline when `ENABLE_HANDS=0`, and
the MoveNet secondary is dropped when `ENABLE_POSE=0`.)

- **`v4l2src` + `jpegdec`** — capture from USB camera, decode MJPEG to raw frames (software path; switch to `nvjpegdec` for hardware decode).
- **`nvstreammux`** — bridges to DeepStream's batched processing model. Even with one source it's required.
- **`nvinfer/primary`** — runs the PeopleNet TensorRT engine on every frame. Output is detection metadata (bboxes + class IDs) attached to the GStreamer buffer.
- **`nvtracker`** — assigns persistent IDs to detected objects across frames. Uses the NvDCF tracker (correlation filter + visual features).
- **`nvdsanalytics`** — pure metadata processing over the tracker IDs. Evaluates the ROI definitions in `analytics_config.txt` and writes results back into the buffer as `NvDsAnalyticsFrameMeta` (per-ROI occupancy) and `NvDsAnalyticsObjInfo` (per-object ROI membership). Zero extra inference cost.
- **`nvinfer/secondary` (MoveNet)** — runs on each person crop (`process-mode=2`, `operate-on-class-ids=0`). Output keypoints arrive as `NvDsInferTensorMeta` on each object meta (`output-tensor-meta=1`, `network-type=100`); the pad probe converts them to image-pixel coordinates and attaches an `NvDsDisplayMeta` with bone lines + joint circles. Dropped when `ENABLE_POSE=0`.
- **`nvinfer` (YOLOX-Body-Head-Hand)** — runs on the full frame to find hands. A pad probe on its src pad decodes the raw YOLOX output (grid + log-space + sigmoid) and applies per-class NMS, attaching each hand as an object for the tertiary GIE to operate on.
- **`nvinfer/tertiary` (MediaPipe Hand Landmark)** — runs on each hand crop, emitting 21 finger keypoints + handedness as `NvDsInferTensorMeta`; the probe projects them to image pixels and attaches `NvDsDisplayMeta`. Both hand GIEs are dropped when `ENABLE_HANDS=0`.
- **`nvdsosd`** — rasterises everything onto the frame in one pass: bounding boxes (with the border colour the probe set based on ROI membership), ROI / line geometry if `analytics_config.txt`'s `osd-mode` is non-zero, and all the `NvDsDisplayMeta` shapes the probe attached (the skeletons).
- **`nvjpegenc`** — encodes the final composited frame to JPEG using NVIDIA's hardware JPEG encoder, fed straight from NVMM NV12. Keeps OpenCV / numpy off the dependency list and avoids a BGR → JPEG re-encode round-trip in Python.
- **`appsink`** — emits pre-encoded JPEG buffers to Python, which the MJPEG stream relays verbatim. A pad probe on `nvdsosd`'s sink also reads the detection + analytics + tensor metadata to populate the `/api/stats` JSON.

The detection metadata travels through the pipeline as `NvDsBatchMeta` attached to each buffer; the Python app reads it via the `pyds` bindings. Frame pixels travel separately and end up in the appsink.

## Storage layout

| Location | Contents | Persistence |
|---|---|---|
| `/usr/lib/nvidia-deepstream/models/peoplenet/` | PeopleNet ONNX (source) + labels | Read-only in sysext; updated via OTA |
| `/usr/lib/nvidia-deepstream/models/movenet/` | MoveNet ONNX (source) | Read-only in sysext; updated via OTA |
| `/usr/lib/nvidia-deepstream/models/handdet/` | YOLOX-Body-Head-Hand ONNX (source) | Read-only in sysext; updated via OTA |
| `/usr/lib/nvidia-deepstream/models/handlandmark/` | MediaPipe Hand Landmark ONNX (source) | Read-only in sysext; updated via OTA |
| `/etc/nvidia-deepstream/` | nvinfer + tracker + analytics configs | Read-only in confext; updated via OTA |
| `/usr/local/bin/app.py` | The Python application | Read-only in sysext; updated via OTA |
| `/usr/libexec/avocado-deepstream-preflight.sh` | Pre-start workarounds (run by systemd) | Read-only in sysext; updated via OTA |
| `/var/lib/nvidia-deepstream/models/peoplenet/` | Staged PeopleNet ONNX + TensorRT engine cache | Persistent; survives OTA; engine rebuilt if ONNX changes |
| `/var/lib/nvidia-deepstream/models/movenet/` | Staged MoveNet ONNX + TensorRT engine cache | Persistent; survives OTA; engine rebuilt if ONNX changes |
| `/var/lib/nvidia-deepstream/models/handdet/` | Staged YOLOX-Hand ONNX + TensorRT engine cache | Persistent; survives OTA; engine rebuilt if ONNX changes |
| `/var/lib/nvidia-deepstream/models/handlandmark/` | Staged MediaPipe Hand Landmark ONNX + TensorRT engine cache | Persistent; survives OTA; engine rebuilt if ONNX changes |
