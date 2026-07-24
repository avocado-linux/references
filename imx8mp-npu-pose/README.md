---
language: Python
targets:
  - ucm-imx8m-plus
topics:
  - npu
  - vision
  - pose-estimation
  - nnstreamer
  - ai-inference
---

# imx8mp-npu-pose — single-person pose estimation on the i.MX8M Plus NPU

Live skeleton tracking with **MoveNet SinglePose Lightning**, quantized to INT8
**by this reference** and offloaded to the i.MX8M Plus Vivante VIP9000 NPU via
NNStreamer's TFLite VX-delegate. One CNN forward pass per frame yields 17 COCO
keypoints; we draw the skeleton over the live video (HDMI and/or a browser).

This is the companion to `imx8mp-npu-nnstreamer` (image classification). Pose is
a better NPU showcase: it is conv-only, fixed-shape, and all post-processing
(decode + draw) happens off the NPU.

## Why MoveNet, given the NPU's limits

The VIP9000 accelerates **per-tensor INT8** conv/depthwise/pool/FC; float ops,
per-channel quantization, dynamic shapes, and in-graph post-processing (NMS,
`TFLite_Detection_PostProcess`) fall back to CPU. MoveNet fits cleanly:

- Pure CNN, static `192×192×3` input → stays on the NPU.
- We quantize it **full-integer INT8** (`quantize-model.py`), the bit this
  reference exists to demonstrate — including the real lesson: **per-tensor
  (the NPU-optimal mode) collapses MoveNet's keypoint confidence to ~0**, so we
  default to **per-channel** (accurate; `PER_TENSOR=1` reproduces the failure).
  Calibration preprocessing is matched to the runtime path (center-crop), and a
  build-time self-check reports keypoint confidence so a bad quant fails early.
- The only non-NPU work is decoding 17 keypoints + drawing — trivial, CPU-side.

MoveNet's SavedModel input is `int32`; `app.py` casts the camera's uint8 tensor
to int32 (`tensor_transform mode=typecast`). Output keypoints are `float32`.

## Pipeline

```
v4l2src → aspectratiocrop 1:1 → tee ──┬── cairooverlay(skeleton) ──┬── waylandsink   (USE_DISPLAY)
                                      │                            └── jpegenc → appsink (WEB_PORT)
                                      └── scale 192 → tensor_converter
                                          → tensor_filter (MoveNet INT8, VX delegate)
                                          → tensor_sink  (Python decodes keypoints)
```

The camera is cropped to a centered square so normalized keypoints map straight
to pixels (no letterbox math).

## Modes (env on the service)

| `USE_DISPLAY` | `WEB_PORT` | Result |
|---|---|---|
| auto/0 | 8080 | headless + **browser skeleton** at `http://<board>:8080/` |
| 1 | 8080 | HDMI skeleton *and* browser |
| 0 | 0 | headless, keypoint count + FPS to journal only |

`USE_NPU=0` runs the identical model on the CPU to compare FPS. `SCORE_THRESH`
(default 0.3) gates which joints/edges are drawn.

## NPU caveats to verify on-device

- **Op placement:** confirm the conv backbone runs on the NPU (VX delegate
  `error_during_*` = 0, no large CPU-fallback fragments). MoveNet's coord-decode
  tail has a couple of reduce/gather ops that may land on CPU — negligible, but
  if the graph fragments badly, PoseNet (pure-conv heatmaps + NNStreamer's
  built-in `mode=pose_estimation` decoder) is the drop-in fallback.
- **uint8 input:** if a MoveNet export resists `inference_input_type=uint8`
  (its SavedModel input is int32), see `quantize-model.py` — wrap with a float
  input layer or fall back to PoseNet.
- **Warmup:** first inference compiles the NPU graph (seconds); FPS ramps after.

## Multi-person later

MoveNet **MultiPose** Lightning (`256×256`, `[1,6,56]` = 6 people × 17 kpts +
box) drops into the same quantizer; only `on_pose` decode + `on_draw` loop over
6 instances change. The pipeline and overlay are already structured for it.

## Usage

See `getting_started.md`.
