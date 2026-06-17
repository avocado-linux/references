#!/usr/bin/env bash
#
# Installs the staged TensorRT engines into the vision-engines extension's
# sysroot. AVOCADO_BUILD_EXT_SYSROOT is provided by the build system.

set -euo pipefail

echo "Installing vision-engines into extension sysroot: $AVOCADO_BUILD_EXT_SYSROOT"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/engines"
cp -r vision-engines/overlay/usr/lib/nvidia-deepstream/engines/* \
      "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/engines/"

echo "Installed."
