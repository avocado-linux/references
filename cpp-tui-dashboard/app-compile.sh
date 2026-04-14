#!/usr/bin/env bash

set -e

echo "============================================"
echo "Building syslog-dashboard with CMake + FTXUI"
echo "============================================"

# ---------------------------------------------------------------------------
# Generate CMake toolchain file from SDK environment
# ---------------------------------------------------------------------------
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

echo "Toolchain file: $TOOLCHAIN_FILE"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
cd app/src

cmake -B build \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build -j"$(nproc)"

echo ""
echo "Build complete: app/src/build/syslog-dashboard"
file build/syslog-dashboard
