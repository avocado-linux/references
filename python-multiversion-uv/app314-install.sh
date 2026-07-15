#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: the sysroot of the extension being installed into.

set -e

echo "[app314] installing interpreter + packages into extension"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app314/packages"
cp -r app314/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app314/packages/"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app314/python"
cp -a app314/python/. "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app314/python/"

echo "[app314] installed"
