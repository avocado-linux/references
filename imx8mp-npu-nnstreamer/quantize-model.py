#!/usr/bin/env python3
"""Post-training INT8 quantization of MobileNetV2 for the i.MX8MP VIP NPU.

Runs inside the Avocado SDK container (x86_64 or aarch64) -- TensorFlow is a
build-time-only dependency here; it is NOT installed on the target. The target
runs the resulting .tflite through nnstreamer's TFLite VX-delegate.

Key choices for the Vivante VIP NPU:
  * Full-integer quantization (TFLITE_BUILTINS_INT8).
  * inference_input_type / output_type = uint8, and the [0,255] -> [-1,1]
    rescaling is baked INTO the graph. So the on-target pipeline can feed raw
    uint8 RGB straight from nnstreamer's tensor_converter -- no normalization
    node, no dtype juggling.
  * _experimental_disable_per_channel = True -> PER-TENSOR weights. The VIP NPU
    accelerates per-tensor INT8; per-channel (TFLite's default) can fall back to
    CPU for some ops. This is the single most important NPU-offload knob.

Emits the .tflite and a matching labels.txt (ImageNet class order) so the
on-device labels line up with the model's outputs.
"""
import glob
import json
import os
import sys

# TF 2.16 defaults to Keras 3, whose functional models crash the MLIR TFLite
# converter ("missing attribute 'value'" / "Failed to infer result type(s)").
# Route tf.keras to legacy Keras 2 (the tf-keras package) BEFORE importing
# tensorflow -- this is the converter-stable path for from_keras_model.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import numpy as np
import tensorflow as tf
from PIL import Image

REP_DIR = sys.argv[1] if len(sys.argv) > 1 else "app/build/rep"
OUT_TFLITE = sys.argv[2] if len(sys.argv) > 2 else "app/build/model/mobilenet_v2_int8.tflite"
OUT_LABELS = sys.argv[3] if len(sys.argv) > 3 else "app/build/model/labels.txt"

IMG = 224
os.makedirs(os.path.dirname(OUT_TFLITE), exist_ok=True)

print(f"TensorFlow {tf.__version__}")

# --- Model: MobileNetV2 with the [0,255]->[-1,1] rescale folded in -----------
base = tf.keras.applications.MobileNetV2(weights="imagenet", input_shape=(IMG, IMG, 3))
inp = tf.keras.Input(shape=(IMG, IMG, 3), dtype=tf.float32)        # raw [0,255]
x = tf.keras.layers.Rescaling(scale=1 / 127.5, offset=-1.0)(inp)   # -> [-1,1]
model = tf.keras.Model(inp, base(x))

# --- Representative dataset (calibration) ------------------------------------
images = sorted(glob.glob(os.path.join(REP_DIR, "*.jpg")))
if not images:
    print(f"ERROR: no calibration images in {REP_DIR} -- run fetch-model.sh first", file=sys.stderr)
    sys.exit(1)
print(f"Calibrating on {len(images)} images from {REP_DIR}")

def representative_dataset():
    for path in images:
        try:
            im = Image.open(path).convert("RGB").resize((IMG, IMG))
        except Exception as e:  # noqa: BLE001
            print(f"  skip {path}: {e}")
            continue
        arr = np.asarray(im, dtype=np.float32)[None, ...]  # [1,224,224,3] in [0,255]
        yield [arr]

# --- Convert: full INT8, uint8 I/O, per-tensor -------------------------------
conv = tf.lite.TFLiteConverter.from_keras_model(model)
conv.optimizations = [tf.lite.Optimize.DEFAULT]
conv.representative_dataset = representative_dataset
conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
conv.inference_input_type = tf.uint8
conv.inference_output_type = tf.uint8
# Per-tensor weights for the VIP NPU (see module docstring).
conv._experimental_disable_per_channel = True

tflite = conv.convert()
with open(OUT_TFLITE, "wb") as f:
    f.write(tflite)
print(f"Wrote {OUT_TFLITE} ({len(tflite) // 1024} KiB)")

# --- Labels (ImageNet 1000, model output order) ------------------------------
idx_path = tf.keras.utils.get_file(
    "imagenet_class_index.json",
    "https://storage.googleapis.com/download.tensorflow.org/data/imagenet_class_index.json",
)
with open(idx_path) as f:
    class_index = json.load(f)
with open(OUT_LABELS, "w") as f:
    for i in range(len(class_index)):
        f.write(class_index[str(i)][1] + "\n")
print(f"Wrote {OUT_LABELS} ({len(class_index)} labels)")
