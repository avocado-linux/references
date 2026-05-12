#!/usr/bin/env bash
set -e

echo "============================================"
echo "Building DeepX Qt5 example (qt-deepx-example)"
echo "============================================"

# Clone the repositories if not already present.
# Use a script-private clone of dx_rt so parallel compile steps (dx-rt,
# dx-app, dx-qt-example) don't race on the same .git/index.lock.
RT_TAG="v3.3.0"
DXRT_SRC="dx_rt_for_qt"

if [ ! -d "$DXRT_SRC" ]; then
    echo "Cloning dx_rt repository into $DXRT_SRC..."
    git clone --recurse-submodules https://github.com/DEEPX-AI/dx_rt.git "$DXRT_SRC"
fi

echo "Checking out dx_rt $RT_TAG..."
git -C "$DXRT_SRC" fetch --tags
git -C "$DXRT_SRC" checkout "$RT_TAG"
git -C "$DXRT_SRC" submodule update --init --recursive

if [ ! -d "qt-deepx-example" ]; then
    echo "Cloning qt-deepx-example repository..."
    git clone https://github.com/embear-engineering/qt-deepx-example.git
else
    echo "Using existing qt-deepx-example directory"
fi

# Resolve cross-compiler from the OE SDK environment
TARGET_ARCH="${OECORE_TARGET_ARCH:-aarch64}"
SYSROOT="${SDKTARGETSYSROOT:-${OECORE_TARGET_SYSROOT}}"
NATIVE_SYSROOT="${OECORE_NATIVE_SYSROOT}"

if [ -z "$SYSROOT" ]; then
    echo "ERROR: SDKTARGETSYSROOT/OECORE_TARGET_SYSROOT is not set"
    exit 1
fi

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

# Step 1: Build and install dx_rt to a local staging prefix for linking
DXRT_STAGING="${AVOCADO_BUILD_DIR}/dx-rt-staging-for-qt"
DXRT_BUILD="${AVOCADO_BUILD_DIR}/dx-rt-build-for-qt"
TOOLCHAIN_FILE="${AVOCADO_BUILD_DIR}/dx-qt-example-toolchain.cmake"

cat > "$TOOLCHAIN_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR ${TARGET_ARCH})

set(CMAKE_C_COMPILER   ${CC_CROSS})
set(CMAKE_CXX_COMPILER ${CXX_CROSS})

set(CMAKE_SYSROOT      ${SYSROOT})
set(CMAKE_FIND_ROOT_PATH ${SYSROOT} ${DXRT_STAGING}/usr/local)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

if [ ! -f "${DXRT_STAGING}/usr/local/lib/libdxrt.so" ] && \
   [ ! -f "${DXRT_STAGING}/usr/local/lib/libdxrt.a" ]; then
    echo "Building dx_rt for linking..."
    mkdir -p "$DXRT_STAGING" "$DXRT_BUILD"

    cmake -S "$DXRT_SRC" -B "$DXRT_BUILD" \
        -G Ninja \
        -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DCMAKE_BUILD_TYPE=Release \
        -DUSE_SERVICE=OFF \
        -DUSE_ORT=OFF \
        -DUSE_PYTHON=OFF \
        -DUSE_DXRT_TEST=OFF

    cmake --build "$DXRT_BUILD" --parallel "$(nproc)"
    DESTDIR="$DXRT_STAGING" cmake --install "$DXRT_BUILD"
    echo "dx_rt built and staged at: $DXRT_STAGING"
else
    echo "Using existing dx_rt staging at: $DXRT_STAGING"
fi

# Step 2: Find qmake or cmake Qt5 from the OE target sysroot
QT5_CMAKE_DIR=$(find "${SYSROOT}" -name "Qt5Config.cmake" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || true)

# Step 3: Build the Qt example
QT_BUILD="${AVOCADO_BUILD_DIR}/dx-qt-example-build"
QT_STAGING="${AVOCADO_BUILD_DIR}/dx-qt-example-staging"
mkdir -p "$QT_BUILD" "$QT_STAGING"

DXRT_INSTALLED_DIR="${DXRT_STAGING}/usr/local"

CMAKE_EXTRA_ARGS=()
if [ -n "$QT5_CMAKE_DIR" ]; then
    CMAKE_EXTRA_ARGS+=("-DQt5_DIR=${QT5_CMAKE_DIR}")
fi
# Qt5Config.cmake (OE cross-build) requires OE_QMAKE_PATH_EXTERNAL_HOST_BINS
# pointing to native Qt host tools (qmake, moc, rcc, uic) from nativesdk-qtbase.
CMAKE_EXTRA_ARGS+=("-DOE_QMAKE_PATH_EXTERNAL_HOST_BINS=${AVOCADO_SDK_PREFIX}/usr/bin")

echo "Configuring qt-deepx-example with CMake..."
cmake -S qt-deepx-example -B "$QT_BUILD" \
    -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_BUILD_TYPE=Release \
    -DDXRT_DIR="$DXRT_INSTALLED_DIR" \
    -DOpenCV_DIR="${SYSROOT}/usr/lib/cmake/opencv4" \
    "${CMAKE_EXTRA_ARGS[@]}"

echo "Building qt-deepx-example..."
cmake --build "$QT_BUILD" --parallel "$(nproc)"

echo "Installing qt-deepx-example to staging directory..."
# CMakeLists.txt has no install() rule; manually stage the binary.
mkdir -p "$QT_STAGING/usr/local/bin"
cp "$QT_BUILD/qt_deepx_example" "$QT_STAGING/usr/local/bin/"

echo "Build complete!"
ls -lh "$QT_STAGING/usr/local/bin/" 2>/dev/null || true
