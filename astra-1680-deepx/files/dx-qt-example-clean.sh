#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX Qt5 example build artifacts"
echo "============================================"

rm -rf \
    "${AVOCADO_BUILD_DIR}/dx-rt-build-for-qt" \
    "${AVOCADO_BUILD_DIR}/dx-rt-staging-for-qt" \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-build" \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-staging" \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-toolchain.cmake" \
    dx_rt_for_qt

echo "Clean complete!"
