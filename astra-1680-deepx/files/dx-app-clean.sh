#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX App (dx_app) build artifacts"
echo "============================================"

rm -rf \
    "${AVOCADO_BUILD_DIR}/dx-rt-build-for-app" \
    "${AVOCADO_BUILD_DIR}/dx-rt-staging-for-app" \
    "${AVOCADO_BUILD_DIR}/dx-app-build" \
    "${AVOCADO_BUILD_DIR}/dx-app-staging" \
    "${AVOCADO_BUILD_DIR}/dx-app-toolchain.cmake" \
    dx_rt_for_app

echo "Clean complete!"
