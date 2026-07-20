#!/usr/bin/env bash

set -e

echo "========================================================"
echo "Building realsense-visualizer (librealsense2 + libmicrohttpd)"
echo "========================================================"

# This must run inside the Avocado SDK cross environment, which exports the
# variables below. Fail early with a clear message if it doesn't, rather than
# emitting a broken toolchain file that fails later as a confusing host build.
if [ -z "${OECORE_TARGET_SYSROOT:-}" ]; then
    echo "OECORE_TARGET_SYSROOT is not set; run this via 'avocado build'" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Generate a CMake toolchain file from the SDK cross environment
# ---------------------------------------------------------------------------
TOOLCHAIN_FILE="/tmp/avocado-toolchain.cmake"

cat > "$TOOLCHAIN_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSROOT "${OECORE_TARGET_SYSROOT}")
set(CMAKE_C_COMPILER ${CROSS_COMPILE}gcc)
set(CMAKE_CXX_COMPILER ${CROSS_COMPILE}g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

echo "Toolchain file: $TOOLCHAIN_FILE"

# ---------------------------------------------------------------------------
# Build (always clean so source changes are never missed)
# ---------------------------------------------------------------------------
cd app/src
rm -rf build

cmake -B build \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build -j"$(nproc)"

echo ""
echo "Build complete: app/src/build/realsense-visualizer"
file build/realsense-visualizer
