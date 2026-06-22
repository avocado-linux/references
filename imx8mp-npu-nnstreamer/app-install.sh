#!/usr/bin/env bash
#
# Install hook: copy the quantized model + labels into the extension sysroot.
# app.py and the systemd unit ride in app/overlay (merged automatically).
#
# AVOCADO_BUILD_EXT_SYSROOT: sysroot of the extension being assembled.

set -euo pipefail

MODEL_DIR="app/build/model"
DEST="$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/imx8mp-npu-nnstreamer"

if [ ! -f "$MODEL_DIR/mobilenet_v2_int8.tflite" ]; then
    echo "ERROR: $MODEL_DIR/mobilenet_v2_int8.tflite missing -- did app-compile.sh run?" >&2
    exit 1
fi

echo "Installing model + labels into the app extension"
mkdir -p "$DEST"
cp "$MODEL_DIR/mobilenet_v2_int8.tflite" "$DEST/"
cp "$MODEL_DIR/labels.txt" "$DEST/"
echo "Installed:"
ls -lh "$DEST/"
