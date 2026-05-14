#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX Qt5 example build artifacts"
echo "============================================"

rm -rf \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-build" \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-staging" \
    "${AVOCADO_BUILD_DIR}/dx-qt-example-toolchain.cmake"

echo "Clean complete!"
