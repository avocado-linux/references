#!/bin/bash
set -e

# Find the Rust target from RUST_TARGET_PATH
for json_file in "$RUST_TARGET_PATH"/*.json; do
    if [ -f "$json_file" ]; then
        json_name=$(basename "$json_file" .json)
        if [[ "$json_name" == "${OECORE_TARGET_ARCH}-"* ]]; then
            RUST_TARGET="$json_name"
            break
        fi
    fi
done

BINARY_PATH="$AVOCADO_BUILD_DIR/target/$RUST_TARGET/release/copper-rs-pose"

if [ ! -f "$BINARY_PATH" ]; then
    echo "Error: Binary not found at $BINARY_PATH"
    exit 1
fi

echo "Installing copper-rs-pose into extension"
install -D -m 755 "$BINARY_PATH" "$AVOCADO_BUILD_EXT_SYSROOT/usr/bin/copper-rs-pose"
echo "Installed: $(file "$AVOCADO_BUILD_EXT_SYSROOT/usr/bin/copper-rs-pose")"

install -D -m 644 "$AVOCADO_BUILD_DIR/yolov8n-pose.safetensors" \
    "$AVOCADO_BUILD_EXT_SYSROOT/usr/share/copper-rs-pose/yolov8n-pose.safetensors"

# The binary links to gstreamer and glibc. The extension must supply these libraries.
"${READELF:-readelf}" -d "$BINARY_PATH" | grep NEEDED || true
