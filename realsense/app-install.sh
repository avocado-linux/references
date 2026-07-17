#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "Installing realsense-visualizer into extension"

DESTDIR="$AVOCADO_BUILD_EXT_SYSROOT" cmake --install app/src/build

echo "realsense-visualizer installed successfully"
