#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: the sysroot of the extension being installed into.

set -e

echo "[app311] installing interpreter + packages into extension"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app311/packages"
cp -r app311/packages/* "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app311/packages/"

mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app311/python"
cp -a app311/python/. "$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/app311/python/"

echo "[app311] installed"
