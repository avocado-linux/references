#!/usr/bin/env bash
#
# Install hook: copy the quantized MoveNet model into the extension sysroot.
# app.py + the systemd unit ride in app/overlay (merged automatically).

set -euo pipefail

MODEL_DIR="app/build/model"
DEST="$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/imx8mp-npu-pose"

if [ ! -f "$MODEL_DIR/movenet_int8.tflite" ]; then
    echo "ERROR: $MODEL_DIR/movenet_int8.tflite missing -- did app-compile.sh run?" >&2
    exit 1
fi

echo "Installing MoveNet INT8 model into the app extension"
mkdir -p "$DEST"
cp "$MODEL_DIR/movenet_int8.tflite" "$DEST/"
echo "Installed:"
ls -lh "$DEST/"
