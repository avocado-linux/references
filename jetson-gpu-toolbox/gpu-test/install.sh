#!/usr/bin/env bash
# AVOCADO_BUILD_EXT_SYSROOT: sysroot of the gpu-test extension being assembled.
set -e

cd "$(dirname "$0")"

install -d "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin"
install -m 0755 vectorAdd "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin/vectorAdd"

echo "Installed: $AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin/vectorAdd"
