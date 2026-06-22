#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "============================================"
echo "Installing DeepX sample models into extension"
echo "============================================"

MODELS_STAGING="${AVOCADO_BUILD_DIR}/dx-models-staging"

if [ ! -d "$MODELS_STAGING/usr/local/lib/dx-models" ]; then
    echo "ERROR: Models staging directory not found: $MODELS_STAGING"
    echo "Run the compile step first."
    exit 1
fi

echo "Copying models to extension sysroot..."
rm -rf "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/lib/dx-models"
cp -a "$MODELS_STAGING/usr" "$AVOCADO_BUILD_EXT_SYSROOT/"

echo "Models installed successfully!"
echo "  Path: ${AVOCADO_BUILD_EXT_SYSROOT}/usr/local/lib/dx-models/"
ls "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/lib/dx-models/"
