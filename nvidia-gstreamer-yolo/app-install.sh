#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "Installing YOLO camera app into extension"

# Copy pip packages
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages"
cp -r app/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/packages/"

# Copy YOLO model
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models"
cp app/overlay/usr/lib/app/models/yolo11n.onnx "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/models/"

echo "YOLO camera app installed successfully"
