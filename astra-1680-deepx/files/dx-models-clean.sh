#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX sample models build artifacts"
echo "============================================"

MODELS_ARCHIVE="${AVOCADO_BUILD_DIR}/models-2_2_1.tar.gz"
MODELS_STAGING="${AVOCADO_BUILD_DIR}/dx-models-staging"

rm -rf "$MODELS_STAGING" "$MODELS_ARCHIVE"

echo "Clean complete!"
