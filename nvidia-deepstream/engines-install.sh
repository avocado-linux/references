#!/usr/bin/env bash
#
# Installs the staged TensorRT engines into the vision-engines extension's
# sysroot. AVOCADO_BUILD_EXT_SYSROOT is provided by the build system.

set -euo pipefail

echo "Installing vision-engines into extension sysroot: $AVOCADO_BUILD_EXT_SYSROOT"

SRC="vision-engines/overlay/usr/lib/nvidia-deepstream/engines"
DST="$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/nvidia-deepstream/engines"
mkdir -p "$DST"

if [ -d "$SRC" ] && ls "$SRC"/*/ >/dev/null 2>&1; then
  cp -r "$SRC"/* "$DST/"
  echo "Installed."
else
  echo "WARNING: no engines staged — vision-engines extension will be empty." >&2
  echo "         vision-app will not start until engines are built on-device" >&2
  echo "         and redeployed. See 'Regenerating engines' in getting_started.md." >&2
fi
