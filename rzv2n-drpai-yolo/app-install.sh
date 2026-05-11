#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -euo pipefail

echo "Installing rzv2n-drpai-yolo into extension"

install -d "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin"
install -m 0755 app/build/cmake/rzv2n-drpai-yolo \
    "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin/rzv2n-drpai-yolo"

# Model bundle + labels are shipped via the overlay; nothing else to copy.

echo "rzv2n-drpai-yolo installed"
