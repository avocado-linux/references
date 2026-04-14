#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "Installing Whisper app into extension"

# Copy Python packages
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages"
cp -r app/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages/"

# Copy pre-downloaded model
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/model"
cp -r app/model/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/model/"

echo "Whisper app installed successfully"
