#!/usr/bin/env bash
#
# SDK "compile" hook (runs inside the Avocado SDK during `avocado build`).
#
# The app itself is Python (nothing to cross-compile). The real build-time work
# here is INT8 quantization: install TensorFlow into an ephemeral venv in the
# SDK container and run quantize-model.py, producing the .tflite + labels.txt
# that app-install.sh copies into the extension sysroot. TensorFlow is NOT
# shipped to the target.

set -euo pipefail

REP_DIR="app/build/rep"
QENV="app/build/qenv"
MODEL_DIR="app/build/model"
TF_PIN="tensorflow==2.16.*"

if [ ! -d "$REP_DIR" ] || [ -z "$(ls -A "$REP_DIR" 2>/dev/null)" ]; then
    echo "ERROR: no representative images in $REP_DIR." >&2
    echo "Run ./fetch-model.sh first (or drop your own .jpg files there)." >&2
    exit 1
fi

echo "============================================"
echo "Quantizing MobileNetV2 -> INT8 for the i.MX8MP NPU"
echo "  SDK host arch: $(uname -m)"
echo "============================================"

# Build the quantization environment in a real venv (NOT `uv pip install
# --target` + PYTHONPATH): the SDK host Python is 3.12, where distutils was
# removed from the stdlib (PEP 632). TensorFlow 2.16 still does `import
# distutils` at load time and relies on setuptools' distutils shim, which is
# injected by a `.pth` file processed at interpreter startup ONLY for genuine
# site dirs. A `--target` dir on PYTHONPATH never gets that processing, so the
# shim never activates. A venv's site-packages does. We also pin setuptools<74:
# 74.0.0 dropped the vendored `_distutils`, so a newer setuptools has no
# distutils to shim in regardless. SETUPTOOLS_USE_DISTUTILS=local (the default)
# makes `import distutils` resolve to setuptools' vendored copy.
export SETUPTOOLS_USE_DISTUTILS=local

# TF 2.16 ships Keras 3 by default, whose functional models crash the MLIR
# TFLite converter ("missing attribute 'value'" / "Failed to infer result
# type(s)") on from_keras_model. Force legacy Keras 2 via the tf-keras package
# (installed below) -- that is the converter-stable path for from_keras_model +
# full-INT8 quantization. Must be set before TensorFlow imports keras.
export TF_USE_LEGACY_KERAS=1

# Clear any prior --target-style qenv so `uv venv` can own the directory.
rm -rf "$QENV"
uv venv --python "$(which python3)" "$QENV"
QPY="$QENV/bin/python"

# uv (nativesdk-uv) resolves the right manylinux wheel for the SDK's arch.
# tensorflow 2.16.x publishes both x86_64 and linux-aarch64 wheels; fall back
# to ARM's tensorflow-aarch64 build if the SDK Python lacks a matching wheel.
# tf-keras==2.16.* is the Keras 2 compat package paired with TF 2.16 (pure
# Python, arch-independent); TF_USE_LEGACY_KERAS=1 above routes tf.keras to it.
if ! uv pip install --python "$QPY" "setuptools<74" "$TF_PIN" "tf-keras==2.16.*" pillow numpy; then
    echo "tensorflow wheel not found for this SDK arch; trying tensorflow-aarch64..."
    uv pip install --python "$QPY" "setuptools<74" \
        "tensorflow-aarch64==2.16.*" "tf-keras==2.16.*" pillow numpy
fi

"$QPY" quantize-model.py \
    "$REP_DIR" \
    "$MODEL_DIR/mobilenet_v2_int8.tflite" \
    "$MODEL_DIR/labels.txt"

echo ""
echo "Quantization complete:"
ls -lh "$MODEL_DIR/"
