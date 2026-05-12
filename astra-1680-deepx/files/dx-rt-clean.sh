#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX Runtime (DXRT) build artifacts"
echo "============================================"

BUILD_DIR="${AVOCADO_BUILD_DIR}/dx-rt-build"
STAGING_DIR="${AVOCADO_BUILD_DIR}/dx-rt-staging"
TOOLCHAIN_FILE="${AVOCADO_BUILD_DIR}/dx-rt-toolchain.cmake"

rm -rf "$BUILD_DIR" "$STAGING_DIR" "$TOOLCHAIN_FILE"

echo "Clean complete!"
