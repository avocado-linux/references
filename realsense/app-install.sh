#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

if [ -z "${AVOCADO_BUILD_EXT_SYSROOT:-}" ]; then
    echo "AVOCADO_BUILD_EXT_SYSROOT is not set; run this via 'avocado build'" >&2
    exit 1
fi

echo "Installing realsense-visualizer into extension"

DESTDIR="$AVOCADO_BUILD_EXT_SYSROOT" cmake --install app/src/build

echo "realsense-visualizer installed successfully"
