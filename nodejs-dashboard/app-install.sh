#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "Installing Node.js app into extension"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app"
cp app/package.json "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/"
cp app/overlay/usr/lib/app/server.js "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/"
cp -r app/node_modules "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app/"

echo "Node.js app installed successfully"
