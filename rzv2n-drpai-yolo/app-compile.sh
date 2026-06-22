#!/usr/bin/env bash

# Cross-compiles the YOLOX-S DRP-AI3 inference app inside the avocado SDK
# container. Clones renesas-rz/rzv_drp-ai_tvm at a pinned tag for the TVM
# headers and the MeraDrpRuntimeWrapper glue, then builds against the
# target sysroot's libtvm_runtime.so (provided by the lib-tvm package).

set -euo pipefail

# Pinned RUHMI tag — bump deliberately. Headers must match the runtime
# version shipped by lib-tvm.bb in meta-rz-drpai (currently 2.5.1).
RUHMI_TAG="v2.5.1"
RUHMI_URL="https://github.com/renesas-rz/rzv_drp-ai_tvm.git"
RUHMI_DIR="app/build/ruhmi"
BUILD_DIR="app/build/cmake"

echo "============================================"
echo "Building rzv2n-drpai-yolo"
echo "  RUHMI: $RUHMI_TAG"
echo "  Sysroot: ${OECORE_TARGET_SYSROOT:-<unset>}"
echo "============================================"

# ---------------------------------------------------------------------------
# Fetch RUHMI source for TVM headers + MeraDrpRuntimeWrapper
# ---------------------------------------------------------------------------
mkdir -p app/build
if [ ! -d "$RUHMI_DIR" ]; then
    echo "Cloning RUHMI $RUHMI_TAG (with submodules for TVM)..."
    git clone --depth 1 --branch "$RUHMI_TAG" --recurse-submodules --shallow-submodules \
        "$RUHMI_URL" "$RUHMI_DIR"
else
    echo "RUHMI source already present at $RUHMI_DIR (skip clone)"
fi

# ---------------------------------------------------------------------------
# Apply RUHMI's DRP-AI environment setup
# ---------------------------------------------------------------------------
# setup/make_drp_env.sh overlays Renesas-patched TVM headers (with kDLDrpAi
# enum + DRP-AI device API) on top of the upstream apache/tvm submodule.
# Idempotent guard via a stamp file — re-running the script after the
# headers are already in place would fail on the symlink creation.
RUHMI_STAMP="$RUHMI_DIR/.avocado-drp-env-setup.done"
if [ ! -f "$RUHMI_STAMP" ]; then
    echo "Setting up RUHMI DRP-AI environment (PRODUCT=V2N)..."
    (cd "$RUHMI_DIR" && PRODUCT=V2N bash setup/make_drp_env.sh)
    touch "$RUHMI_STAMP"
else
    echo "RUHMI DRP-AI env already set up (skip)"
fi

# ---------------------------------------------------------------------------
# Generate CMake toolchain file from SDK environment
# ---------------------------------------------------------------------------
TOOLCHAIN_FILE="/tmp/avocado-rzv2n-toolchain.cmake"

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

echo "Toolchain file: $TOOLCHAIN_FILE"

# ---------------------------------------------------------------------------
# Configure + build
# ---------------------------------------------------------------------------
RUHMI_ABS="$(cd "$RUHMI_DIR" && pwd)"

cmake -S app/src -B "$BUILD_DIR" \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release \
    -DRUHMI_DIR="$RUHMI_ABS"

cmake --build "$BUILD_DIR" -j"$(nproc)"

echo ""
echo "Build complete: $BUILD_DIR/rzv2n-drpai-yolo"
file "$BUILD_DIR/rzv2n-drpai-yolo"
