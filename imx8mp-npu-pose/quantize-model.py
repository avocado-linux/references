#!/usr/bin/env python3
"""Per-tensor INT8 quantization of MoveNet SinglePose Lightning for the i.MX8MP VIP NPU.

Runs inside the Avocado SDK (build-time only; TensorFlow is NOT shipped to the
target). MoveNet is a single-shot pose estimator: one CNN forward pass yields 17
COCO keypoints (y, x, score) for the most prominent person -- a great NPU demo
because it is conv-only, fixed-shape, and the only post-processing (drawing the
skeleton) happens outside the model.

Why these choices, given the VIP9000's limits:
  * Full-integer INT8 (TFLITE_BUILTINS_INT8): the NPU only accelerates integer
    ops; any float op falls back to CPU.
  * inference_input_type = uint8: the camera feeds raw uint8 RGB straight from
    nnstreamer's tensor_converter -- no normalization node on-device. (Output is
    left float32: the 17 keypoint coords/scores need the precision, and it is a
    tiny tensor so the boundary dequant is negligible.)
  * Per-channel weights (TFLite default; PER_TENSOR=1 to force per-tensor). The
    VIP NPU prefers per-tensor, but MoveNet's depthwise-heavy backbone collapses
    to ~0 confidence under per-tensor -- the headline quantization lesson here.
    Per-channel keeps accuracy; measure how much stays on the NPU and tune.
  * Calibration preprocessing MUST match app.py's runtime path (center-crop to
    square + resize), or the activation ranges are calibrated on a different
    input distribution and the INT8 output degenerates.
  * A build-time self-check runs the INT8 model on calib images and reports the
    best keypoint confidence, so a bad quantization fails at build, not on-device.

MoveNet's SavedModel input is int32 [1,192,192,3] (0..255). We expose a uint8
input to the converter; if a particular MoveNet export resists uint8 I/O, see
README -- PoseNet (pure-conv heatmaps) is the proven fallback.

Multi-person later: MoveNet MultiPose Lightning (256x256, [1,6,56]) drops into the
same converter; only the decode in app.py changes.
"""
import glob
import os
import sys

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import numpy as np
import tensorflow as tf
from PIL import Image

SAVED_MODEL = sys.argv[1] if len(sys.argv) > 1 else "app/build/movenet"
REP_DIR = sys.argv[2] if len(sys.argv) > 2 else "app/build/rep"
OUT_TFLITE = sys.argv[3] if len(sys.argv) > 3 else "app/build/model/movenet_int8.tflite"

IMG = 192  # SinglePose Lightning input
os.makedirs(os.path.dirname(OUT_TFLITE), exist_ok=True)

print(f"TensorFlow {tf.__version__}")

images = sorted(glob.glob(os.path.join(REP_DIR, "*.jpg")))
if not images:
    print(f"ERROR: no calibration images in {REP_DIR} -- run fetch-model.sh first", file=sys.stderr)
    sys.exit(1)
print(f"Calibrating on {len(images)} images from {REP_DIR}")


def _center_square_resize(im):
    """Center-crop to square, then resize to IMGxIMG.

    MUST match app.py's on-device preprocessing (aspectratiocrop 1:1 + videoscale).
    The earlier resize_with_pad added black bars the runtime never sees, so the
    activation ranges were calibrated on a different distribution -> degenerate
    INT8 output. Center-crop matches the camera path.
    """
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    im = im.crop((left, top, left + s, top + s)).resize((IMG, IMG))
    return np.asarray(im, dtype=np.float32)


def representative_dataset():
    for path in images:
        try:
            im = Image.open(path).convert("RGB")
        except Exception as e:  # noqa: BLE001
            print(f"  skip {path}: {e}")
            continue
        arr = _center_square_resize(im)[None, ...]             # [1,192,192,3], 0..255
        yield [tf.cast(arr, tf.int32)]                         # MoveNet SavedModel takes int32


# Per-channel by default. Per-tensor is NPU-optimal but MoveNet's depthwise-heavy
# backbone loses too much accuracy under it (keypoint scores collapse to ~0) --
# the headline quantization lesson of this reference. PER_TENSOR=1 to reproduce.
PER_TENSOR = os.environ.get("PER_TENSOR", "0") == "1"

conv = tf.lite.TFLiteConverter.from_saved_model(SAVED_MODEL)
conv.optimizations = [tf.lite.Optimize.DEFAULT]
conv.representative_dataset = representative_dataset
conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
if PER_TENSOR:
    conv._experimental_disable_per_channel = True
conv.inference_input_type = tf.uint8            # MoveNet's int32 input may persist; app.py typecasts
# inference_output_type left float32 (keypoint coords/scores precision)

tflite = conv.convert()
with open(OUT_TFLITE, "wb") as f:
    f.write(tflite)
print(f"Wrote {OUT_TFLITE} ({len(tflite) // 1024} KiB)  quant={'per-tensor' if PER_TENSOR else 'per-channel'}")

# --- Build-time self-check: run the INT8 model on a few calibration images and
#     report the best keypoint confidence. Catches a degenerate quantization
#     HERE (at build) instead of on the board. Scores stay modest if the calib
#     set has no people -- the loud failure mode is best ~0.0 with all keypoints
#     pinned to a corner (what per-tensor produced). ---
interp = tf.lite.Interpreter(model_content=tflite)
interp.allocate_tensors()
ind, outd = interp.get_input_details()[0], interp.get_output_details()[0]
best = 0.0
for path in images[:10]:
    try:
        arr = _center_square_resize(Image.open(path).convert("RGB"))[None, ...]
    except Exception:  # noqa: BLE001
        continue
    interp.set_tensor(ind["index"], arr.astype(ind["dtype"]))
    interp.invoke()
    kp = interp.get_tensor(outd["index"]).reshape(-1, 3)[:17]
    best = max(best, float(kp[:, 2].max()))
print(f"Self-check: best keypoint score over {min(10, len(images))} calib images = {best:.3f}")
if best < 0.15:
    print("WARNING: INT8 model looks degenerate (scores ~0). Try PER_TENSOR=0 (default),"
          " and put real people frames in the calibration set (app/build/rep/).", file=sys.stderr)
