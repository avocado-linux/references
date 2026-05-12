#!/usr/bin/env bash
set -e

echo "============================================"
echo "Building DeepX App (dx_app)"
echo "============================================"

RT_TAG="v3.3.0"
APP_TAG="v3.1.0"

# Use a script-private clone of dx_rt so parallel compile steps (dx-rt,
# dx-app, dx-qt-example) don't race on the same .git/index.lock.
DXRT_SRC="dx_rt_for_app"

if [ ! -d "$DXRT_SRC" ]; then
    echo "Cloning dx_rt repository into $DXRT_SRC..."
    git clone --recurse-submodules https://github.com/DEEPX-AI/dx_rt.git "$DXRT_SRC"
fi

echo "Checking out dx_rt $RT_TAG..."
git -C "$DXRT_SRC" fetch --tags
git -C "$DXRT_SRC" checkout "$RT_TAG"
git -C "$DXRT_SRC" submodule update --init --recursive

if [ ! -d "dx_app" ]; then
    echo "Cloning dx_app repository..."
    git clone --recurse-submodules https://github.com/DEEPX-AI/dx_app.git
fi

echo "Checking out dx_app $APP_TAG..."
git -C dx_app fetch --tags
git -C dx_app checkout "$APP_TAG"
git -C dx_app submodule update --init --recursive

# dx_app v3.1.0 hardcodes CMAKE_CXX_STANDARD=14 for non-MSVC builds.
# The code already uses C++17 features (structured bindings) and
# std::experimental::filesystem which requires libstdc++fs - a library
# that no longer exists as separate in GCC 9+.  Build with C++17 so
# std::filesystem is used instead (merged into libstdc++ in GCC 9+).
python3 - <<'PYEOF'
import pathlib
cmake = pathlib.Path("dx_app/CMakeLists.txt")
src = cmake.read_text()
patched = False

# Fix 1: change C++ standard from 14 to 17 for non-MSVC (cross-compile) builds
old1 = "set(CMAKE_CXX_STANDARD 14)\nif(MSVC)\nset(CMAKE_CXX_STANDARD 17)\nendif()"
new1 = "set(CMAKE_CXX_STANDARD 17)"
if old1 in src:
    src = src.replace(old1, new1, 1)
    patched = True
    print("Patched dx_app/CMakeLists.txt: CMAKE_CXX_STANDARD set to 17")
elif "set(CMAKE_CXX_STANDARD 17)" in src and "set(CMAKE_CXX_STANDARD 14)" not in src:
    print("dx_app/CMakeLists.txt already uses C++17, skipping fix 1")
else:
    print("WARNING: Could not apply C++ standard fix to dx_app/CMakeLists.txt")

if patched:
    cmake.write_text(src)
PYEOF

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
DXRT_STAGING="${AVOCADO_BUILD_DIR}/dx-rt-staging-for-app"
DXRT_BUILD="${AVOCADO_BUILD_DIR}/dx-rt-build-for-app"
TOOLCHAIN_FILE="${AVOCADO_BUILD_DIR}/dx-app-toolchain.cmake"

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

# Step 2: Build dx_app against the staged dx_rt and the OE target sysroot
APP_BUILD="${AVOCADO_BUILD_DIR}/dx-app-build"
APP_STAGING="${AVOCADO_BUILD_DIR}/dx-app-staging"
mkdir -p "$APP_BUILD" "$APP_STAGING"

DXRT_INSTALLED_DIR="${DXRT_STAGING}/usr/local"

echo "Configuring dx_app with CMake..."
cmake -S dx_app -B "$APP_BUILD" \
    -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_BUILD_TYPE=Release \
    -DDXRT_INSTALLED_DIR="$DXRT_INSTALLED_DIR" \
    -DOpenCV_DIR="${SYSROOT}/usr/lib/cmake/opencv4" \
    -DWITH_VAAPI=OFF \
    -DUSE_DXAPP_TEST=OFF

echo "Building dx_app..."
cmake --build "$APP_BUILD" --target install --parallel "$(nproc)"

echo "Installing dx_app to staging directory..."
DESTDIR="$APP_STAGING" cmake --install "$APP_BUILD"

echo "Build complete!"
ls -lh "$APP_STAGING/usr/local/bin/" 2>/dev/null || true
