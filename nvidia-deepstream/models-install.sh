#!/usr/bin/env bash
#
# Installs the staged ONNX model files into the vision-models extension's
# sysroot. AVOCADO_BUILD_EXT_SYSROOT is provided by the build system.

set -euo pipefail

echo "Installing vision-models ONNX files into extension sysroot: $AVOCADO_BUILD_EXT_SYSROOT"

# PeopleNet (primary GIE), MoveNet (secondary pose GIE), YOLOX-Hand
# (secondary hand detector), and MediaPipe Hand Landmark (tertiary GIE)
# ONNX files staged during models-compile.sh.
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/models"
cp -r vision-models/overlay/usr/lib/nvidia-deepstream/models/* \
      "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/models/"

echo "Installed."
