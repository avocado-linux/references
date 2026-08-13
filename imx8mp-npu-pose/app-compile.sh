#!/usr/bin/env bash
#
# SDK "compile" hook: INT8-quantize MoveNet in an ephemeral venv inside the SDK
# container and emit movenet_int8.tflite. TensorFlow is build-time only; it is
# NOT shipped to the target (the target runs the .tflite via nnstreamer's TFLite
# VX delegate).

set -euo pipefail

MODEL_DIR="app/build/movenet"
REP_DIR="app/build/rep"
QENV="app/build/qenv"
OUT_DIR="app/build/model"
TF_PIN="tensorflow==2.16.*"

# Fetch the SavedModel and calibration inputs if they are not there yet, so
# `avocado build` works on a fresh clone (and in CI) without a manual pre-step.
# fetch-model.sh is idempotent -- it skips anything already downloaded. Drop
# your own .jpg files into $REP_DIR beforehand and they are used as-is.
if [ ! -f "$MODEL_DIR/saved_model.pb" ] || [ -z "$(ls -A "$REP_DIR"/*.jpg 2>/dev/null)" ]; then
    echo "MoveNet SavedModel or calibration images missing; fetching them."
    ./fetch-model.sh
fi

echo "============================================"
echo "Quantizing MoveNet SinglePose Lightning -> INT8 for the i.MX8MP NPU"
echo "  SDK host arch: $(uname -m)"
echo "============================================"

# Real venv (not --target+PYTHONPATH) so setuptools' distutils shim activates on
# Python 3.12 (PEP 632 removed stdlib distutils; TF 2.16 still imports it).
# setuptools<74 still vendors _distutils; 74+ dropped it.
export SETUPTOOLS_USE_DISTUTILS=local

rm -rf "$QENV"
uv venv --python "$(which python3)" "$QENV"
QPY="$QENV/bin/python"

if ! uv pip install --python "$QPY" "setuptools<74" "$TF_PIN" pillow numpy; then
    echo "tensorflow wheel not found for this SDK arch; trying tensorflow-aarch64..."
    uv pip install --python "$QPY" "setuptools<74" "tensorflow-aarch64==2.16.*" pillow numpy
fi

"$QPY" quantize-model.py "$MODEL_DIR" "$REP_DIR" "$OUT_DIR/movenet_int8.tflite"

echo ""
echo "Quantization complete:"
ls -lh "$OUT_DIR/"
