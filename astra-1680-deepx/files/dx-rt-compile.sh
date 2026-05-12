#!/usr/bin/env bash
set -e

echo "============================================"
echo "Building DeepX Runtime (DXRT)"
echo "============================================"

RT_TAG="v3.3.0"

# Clone the dx_rt repository with submodules if not already present
if [ ! -d "dx_rt" ]; then
    echo "Cloning dx_rt repository..."
    git clone --recurse-submodules https://github.com/DEEPX-AI/dx_rt.git
fi

echo "Checking out $RT_TAG..."
git -C dx_rt fetch --tags
git -C dx_rt checkout "$RT_TAG"
git -C dx_rt submodule update --init --recursive

# Resolve cross-compiler from the OE SDK environment
TARGET_ARCH="${OECORE_TARGET_ARCH:-aarch64}"
SYSROOT="${SDKTARGETSYSROOT:-${OECORE_TARGET_SYSROOT}}"
NATIVE_SYSROOT="${OECORE_NATIVE_SYSROOT}"

if [ -z "$SYSROOT" ]; then
    echo "ERROR: SDKTARGETSYSROOT/OECORE_TARGET_SYSROOT is not set"
    exit 1
fi

# Find the cross C/C++ compiler from the SDK
CC_CROSS=""
CXX_CROSS=""
if [ -n "$CROSS_COMPILE" ]; then
    CC_CROSS="${CROSS_COMPILE}gcc"
    CXX_CROSS="${CROSS_COMPILE}g++"
fi

if [ -n "$NATIVE_SYSROOT" ] && [ -z "$CC_CROSS" ]; then
    CC_CROSS=$(find "$NATIVE_SYSROOT/usr/bin" -name "*-linux*-gcc" 2>/dev/null | head -1)
    CXX_CROSS=$(find "$NATIVE_SYSROOT/usr/bin" -name "*-linux*-g++" 2>/dev/null | head -1)
fi

if [ -z "$CC_CROSS" ]; then
    echo "ERROR: Could not determine cross-compiler. Set CROSS_COMPILE."
    exit 1
fi

echo "Cross C compiler:   $CC_CROSS"
echo "Cross C++ compiler: $CXX_CROSS"
echo "Target sysroot:     $SYSROOT"

# Write a CMake toolchain file for the OE SDK cross-compilation environment
TOOLCHAIN_FILE="${AVOCADO_BUILD_DIR}/dx-rt-toolchain.cmake"
cat > "$TOOLCHAIN_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR ${TARGET_ARCH})

set(CMAKE_C_COMPILER   ${CC_CROSS})
set(CMAKE_CXX_COMPILER ${CXX_CROSS})

set(CMAKE_SYSROOT      ${SYSROOT})
set(CMAKE_FIND_ROOT_PATH ${SYSROOT})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# Install prefix inside the staging area
set(CMAKE_INSTALL_PREFIX /usr/local)
EOF

# Staging directory for the built artifacts
STAGING_DIR="${AVOCADO_BUILD_DIR}/dx-rt-staging"
mkdir -p "$STAGING_DIR"

BUILD_DIR="${AVOCADO_BUILD_DIR}/dx-rt-build"
mkdir -p "$BUILD_DIR"

echo "Configuring DXRT with CMake..."
cmake -S dx_rt -B "$BUILD_DIR" \
    -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_SERVICE=ON \
    -DUSE_ORT=OFF \
    -DUSE_PYTHON=OFF \
    -DUSE_DXRT_TEST=OFF

echo "Building DXRT..."
cmake --build "$BUILD_DIR" --parallel "$(nproc)"

echo "Installing DXRT to staging directory..."
DESTDIR="$STAGING_DIR" cmake --install "$BUILD_DIR"

echo "Build complete!"
echo "Artifacts in: $STAGING_DIR"
ls -lh "$STAGING_DIR/usr/local/lib/"libdxrt* 2>/dev/null || true
ls -lh "$STAGING_DIR/usr/local/bin/"dxrtd* 2>/dev/null || true
