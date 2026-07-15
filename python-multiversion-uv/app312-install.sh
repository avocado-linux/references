#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: the sysroot of the extension being installed into.

set -e

echo "[app312] installing packages into extension"

# No interpreter to ship: app312 runs on the device's system /usr/bin/python3.
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app312/packages"
cp -r app312/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app312/packages/"

echo "[app312] installed"
