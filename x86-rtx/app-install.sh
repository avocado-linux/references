#!/usr/bin/env bash
# Copy pip deps + the generated ONNX model into the extension sysroot. Runs
# inside the SDK container after app-compile.sh. Static files (app.py, the
# systemd unit) are handled by the `overlay:` mechanism.
set -euo pipefail

: "${AVOCADO_BUILD_EXT_SYSROOT:?AVOCADO_BUILD_EXT_SYSROOT not set}"

echo "Installing x86-rtx inference app into extension"

# Runtime pip deps
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages"
cp -r app/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages/"

# Demo model
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models"
cp app/build/model.onnx "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models/"

echo "Installed."
