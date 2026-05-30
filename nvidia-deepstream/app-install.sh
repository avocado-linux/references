#!/usr/bin/env bash
#
# Installs the staged model artifacts into the app extension's sysroot.
# AVOCADO_BUILD_EXT_SYSROOT is provided by the build system.

set -euo pipefail

echo "Installing DeepStream reference into extension sysroot: $AVOCADO_BUILD_EXT_SYSROOT"

# PeopleNet (primary GIE), MoveNet (secondary pose GIE), YOLOX-Hand
# (secondary hand detector), and MediaPipe Hand Landmark (tertiary GIE)
# ONNX files staged during app-compile.sh.
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/models"
cp -r app/overlay/usr/lib/nvidia-deepstream/models/* \
      "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/models/"

echo "Installed."
