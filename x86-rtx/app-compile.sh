#!/usr/bin/env bash
# Stage runtime pip deps and generate the demo ONNX model. Runs inside the SDK
# container during `avocado build`; outputs are consumed by app-install.sh.
#
# Runtime deps NOT in the feed: flask (dashboard) + cuda-python (device buffer
# marshalling for TensorRT-RTX execution). numpy comes from the feed
# (python3-numpy) and tensorrt_rtx from avocado-ext-nvidia-tensorrt-rtx.
set -euo pipefail

PY="$(which python3)"

echo "Installing runtime Python dependencies..."
mkdir -p app/packages app/build
uv pip install --target app/packages --python "$PY" flask cuda-python

echo "Generating demo ONNX model..."
# onnx + numpy are build-time only (used to synthesize the model), so keep them
# out of the target package set.
uv pip install --target app/build/gendeps --python "$PY" onnx numpy
PYTHONPATH="app/build/gendeps" "$PY" app/gen_model.py app/build/model.onnx

echo "Compile step complete."
