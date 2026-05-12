#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "============================================"
echo "Installing DeepX App (dx_app) into extension"
echo "============================================"

APP_STAGING="${AVOCADO_BUILD_DIR}/dx-app-staging"

if [ ! -d "$APP_STAGING/usr/local" ]; then
    echo "ERROR: Staging directory not found: $APP_STAGING"
    echo "Run the compile step first."
    exit 1
fi

echo "Copying dx_app binaries..."
cp -a "$APP_STAGING/usr" "$AVOCADO_BUILD_EXT_SYSROOT/"

echo "dx_app installed successfully!"
echo "  Binaries: ${AVOCADO_BUILD_EXT_SYSROOT}/usr/local/bin/"
