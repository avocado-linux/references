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

if [ -z "$RUST_TARGET" ]; then
    echo "Error: Could not find Rust target for $OECORE_TARGET_ARCH"
    exit 1
fi

echo "Compiling copper-rs-pose for target: $RUST_TARGET"

# Keep the crate cache and the build output in the SDK volume
# ($AVOCADO_BUILD_DIR). The project directory is a host file share, and
# a cargo build of this size on it is very slow.
export CARGO_HOME="$AVOCADO_BUILD_DIR/cargo-home"
export CARGO_TARGET_DIR="$AVOCADO_BUILD_DIR/target"

# YOLOv8n-pose weights (Ultralytics, AGPL-3.0), converted for Candle.
# Pinned to one commit and examined with sha256. Downloaded once.
MODEL="$AVOCADO_BUILD_DIR/yolov8n-pose.safetensors"
MODEL_URL="https://huggingface.co/lmz/candle-yolo-v8/resolve/be388c6fab95ae3035a039070e1b883b9c5a1325/yolov8n-pose.safetensors"
MODEL_SHA256="08c76047b41744c027c8150e81d1dbbd94f996656cf5be266491367ae7fad072"
if ! echo "$MODEL_SHA256  $MODEL" | sha256sum -c --status 2>/dev/null; then
    echo "Downloading model: $MODEL_URL"
    curl -fL --retry 3 -o "$MODEL.part" "$MODEL_URL"
    echo "$MODEL_SHA256  $MODEL.part" | sha256sum -c -
    mv "$MODEL.part" "$MODEL"
fi

cd app

# Clear any rustflags that might cause conflicts with our .cargo/config.toml
unset RUSTFLAGS
unset CARGO_BUILD_RUSTFLAGS
# Clear target-specific rustflags for all possible targets
for var in $(env | grep -o 'CARGO_TARGET_[A-Z0-9_]*_RUSTFLAGS'); do
    unset "$var"
done

# Remove any existing config that might conflict
rm -rf .cargo

# Create config.toml with cross-compilation settings
mkdir -p .cargo
cat > .cargo/config.toml << EOF
[target.$RUST_TARGET]
rustflags = ["--sysroot=$SDKTARGETSYSROOT/usr", "-C", "link-arg=--sysroot=$SDKTARGETSYSROOT"]
EOF

# gstreamer-sys finds the target gstreamer through pkg-config in the SDK sysroot.
export PKG_CONFIG_ALLOW_CROSS=1

# Copper declares rust-version 1.95. The SDK rust is older, and the code builds
# with it. The exact pins in Cargo.toml keep this bypass stable.
cargo build --release --locked --ignore-rust-version --target "$RUST_TARGET"
