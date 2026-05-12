#!/usr/bin/env bash
set -e

echo "============================================"
echo "Downloading DeepX sample models"
echo "============================================"

MODELS_URL="https://sdk.deepx.ai/res/models/models-2_2_1.tar.gz"
MODELS_ARCHIVE="${AVOCADO_BUILD_DIR}/models-2_2_1.tar.gz"
MODELS_STAGING="${AVOCADO_BUILD_DIR}/dx-models-staging"
MODELS_DEST="${MODELS_STAGING}/usr/local/lib/dx-models"

# curl is installed via nativesdk-curl into the SDK prefix
CURL="${AVOCADO_SDK_PREFIX}/usr/bin/curl"

rm -rf "$MODELS_STAGING"
mkdir -p "$MODELS_DEST"

if [ ! -f "$MODELS_ARCHIVE" ]; then
    echo "Downloading models archive..."
    "$CURL" -fL --retry 3 -o "$MODELS_ARCHIVE" "$MODELS_URL"
else
    echo "Using cached archive: $MODELS_ARCHIVE"
fi

echo "Extracting models..."
# tar -xzf "$MODELS_ARCHIVE" -C "$MODELS_DEST" --strip-components=1
# Extrac tonly YoloV8N.dxnn to save space
tar -xzf "$MODELS_ARCHIVE" --strip-components=1 \
    --wildcards --no-anchored \
    -C "$MODELS_DEST" \
    '[Yy][Oo][Ll][Oo][Vv][89]*'

echo "Models extracted to: $MODELS_DEST"
ls "$MODELS_DEST"
