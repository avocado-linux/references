#!/usr/bin/env bash
#
# SDK "compile" hook: cross-compile the C++ runner against the target sysroot.
# Phase 1 does NOT export models here -- segmentation.pte is committed to the
# repo (see tools/export_model.py), so this step is just a fast C++ build with
# no PyTorch/pip involved.

set -euo pipefail

if [ ! -f app/models/segmentation.pte ]; then
    echo "ERROR: app/models/segmentation.pte is missing." >&2
    echo "Generate it once (offline) and commit it:" >&2
    echo "    pip install --extra-index-url https://download.pytorch.org/whl/cpu \\" >&2
    echo "        torch torchvision 'executorch==1.3.*'" >&2
    echo "    python tools/export_model.py" >&2
    exit 1
fi

echo "Building executorch-segmentation (C++ cross-compile)"

# CMake toolchain file generated from the SDK environment (same pattern as the
# cpp-tui-dashboard reference).
TOOLCHAIN_FILE="/tmp/avocado-toolchain.cmake"
cat > "$TOOLCHAIN_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSROOT ${OECORE_TARGET_SYSROOT})
set(CMAKE_C_COMPILER ${CROSS_COMPILE}gcc)
set(CMAKE_CXX_COMPILER ${CROSS_COMPILE}g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

cd app/src
cmake -B build \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build -j"$(nproc)"

echo ""
echo "Build complete:"
file build/executorch-segmentation
