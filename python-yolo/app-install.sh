#!/usr/bin/env bash
# Copy pip packages + ONNX model into the extension sysroot. Runs inside the
# SDK container after app-compile.sh.

set -euo pipefail

: "${AVOCADO_BUILD_EXT_SYSROOT:?AVOCADO_BUILD_EXT_SYSROOT not set}"

echo "Installing object-detection app into extension"

# Python deps
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages"
cp -r app/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages/"

# Model
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models"
cp app/overlay/usr/lib/app/models/yolov8n-416.onnx \
   "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models/"

echo "Installed."
