#!/usr/bin/env bash

# Cross-compiles the YOLOv3 DRP-AI3 inference app inside the avocado SDK
# container. Clones renesas-rz/rzv_drp-ai_tvm (RUHMI) at a pinned release for
# the TVM/MERA2 headers and the MeraDrpRuntimeWrapper glue, then builds
# against the target sysroot's MERA2 / DRP-AI TVM runtime (lib-ruhmi).

set -euo pipefail

# Pinned RUHMI release — bump deliberately. It must match the runtime that
# lib-ruhmi ships (RUHMI_R2026-06) and the model in fetch-model.sh.
RUHMI_TAG="Release-2026-06-30"
RUHMI_URL="https://github.com/renesas-rz/rzv_drp-ai_tvm.git"
RUHMI_DIR="app/build/ruhmi"
# mera_runtime.h includes asio (header-only); RUHMI's own setup clones it.
ASIO_TAG="asio-1-30-2"
ASIO_URL="https://github.com/chriskohlhoff/asio.git"
ASIO_DIR="app/build/asio"
BUILD_DIR="app/build/cmake"

echo "============================================"
echo "Building rzv2n-drpai-yolo"
echo "  RUHMI: $RUHMI_TAG"
echo "  Sysroot: ${OECORE_TARGET_SYSROOT:-<unset>}"
echo "============================================"

mkdir -p app/build
if [ ! -d "$RUHMI_DIR" ]; then
    echo "Cloning RUHMI $RUHMI_TAG (with the tvm submodule)..."
    git clone --depth 1 --branch "$RUHMI_TAG" "$RUHMI_URL" "$RUHMI_DIR"
    git -C "$RUHMI_DIR" submodule update --init --depth 1 tvm
    git -C "$RUHMI_DIR/tvm" submodule update --init --depth 1 \
        3rdparty/dlpack 3rdparty/dmlc-core
fi
if [ ! -d "$ASIO_DIR" ]; then
    git clone --depth 1 --branch "$ASIO_TAG" "$ASIO_URL" "$ASIO_DIR"
fi

# RUHMI's setup overlays Renesas-patched TVM runtime headers (kDLDrpAi and
# the DRP-AI device API) on the tvm submodule. Idempotent: cp overwrites.
cp "$RUHMI_DIR"/setup/include/*.h "$RUHMI_DIR"/tvm/include/tvm/runtime/

TOOLCHAIN_FILE="app/build/toolchain.cmake"
cat > "$TOOLCHAIN_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_SYSROOT ${OECORE_TARGET_SYSROOT})
set(CMAKE_C_COMPILER ${CROSS_COMPILE}gcc)
set(CMAKE_CXX_COMPILER ${CROSS_COMPILE}g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

cmake -S app/src -B "$BUILD_DIR" \
    -DCMAKE_TOOLCHAIN_FILE="$(pwd)/$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release \
    -DRUHMI_DIR="$(cd "$RUHMI_DIR" && pwd)" \
    -DASIO_DIR="$(cd "$ASIO_DIR" && pwd)"

cmake --build "$BUILD_DIR" -j"$(nproc)"

echo ""
echo "Build complete: $BUILD_DIR/rzv2n-drpai-yolo"
file "$BUILD_DIR/rzv2n-drpai-yolo"
