#!/usr/bin/env bash
# Cross-compile vectorAdd.cu against the L4T cudart in the SDK target sysroot.
#
# Inherited SDK env (set by avocado sdk run -E):
#   CXX                    = aarch64-avocado-linux-g++ <flags>
#   CROSS_COMPILE          = aarch64-avocado-linux-
#   OECORE_NATIVE_SYSROOT  = host-arch sysroot (where nvcc lives)
#   OECORE_TARGET_SYSROOT  = aarch64 sysroot (cudart headers + stubs)
set -e

cd "$(dirname "$0")"

# nvcc -ccbin needs the bare cross g++ binary, not CXX (which carries flags).
CCBIN=$(echo "$CXX" | awk '{print $1}')

# Resolve nvcc — nativesdk-cuda-nvcc lands it under the SDK's host bin path.
NVCC=$(command -v nvcc || true)
if [ -z "$NVCC" ]; then
    for cand in \
        "$OECORE_NATIVE_SYSROOT/usr/bin/nvcc" \
        "$OECORE_NATIVE_SYSROOT/usr/local/cuda/bin/nvcc"; do
        [ -x "$cand" ] && NVCC="$cand" && break
    done
fi
if [ -z "$NVCC" ]; then
    echo "ERROR: nvcc not found. Make sure nativesdk-cuda-nvcc is installed." >&2
    exit 1
fi

# cuda-cudart-dev installs into /usr/local/cuda-<ver>/{include,lib} in the
# target sysroot, not /usr/{include,lib}. Glob to stay version-agnostic.
CUDA_TARGET_DIR=$(echo "$OECORE_TARGET_SYSROOT"/usr/local/cuda-* | awk '{print $1}')
if [ ! -d "$CUDA_TARGET_DIR/include" ]; then
    echo "ERROR: cuda_runtime.h not found under $OECORE_TARGET_SYSROOT/usr/local/cuda-*/" >&2
    echo "       Make sure cuda-cudart-dev is in sdk.compile.gpu-test.packages." >&2
    exit 1
fi

echo "Using nvcc:        $NVCC"
echo "Using ccbin:       $CCBIN"
echo "Target sysroot:    $OECORE_TARGET_SYSROOT"
echo "CUDA target dir:   $CUDA_TARGET_DIR"

# cuda-cudart-dev / tegra-libraries-cuda land libcudart.so.12 under
# /usr/local/cuda-<ver>/lib on the device, which isn't in the default
# dynamic-linker search path. Bake the runtime path into the binary as
# RPATH so the loader can find it without LD_LIBRARY_PATH or an
# /etc/ld.so.conf.d/ drop-in (which would require a confext).
CUDA_RUNTIME_DIR=/usr/local/$(basename "$CUDA_TARGET_DIR")/lib

# sm_87 = AGX Orin / Orin NX / Orin Nano (Ampere, GA10B).
"$NVCC" \
    -ccbin "$CCBIN" \
    -arch=sm_87 \
    -Xcompiler "--sysroot=$OECORE_TARGET_SYSROOT" \
    -Xlinker  "--sysroot=$OECORE_TARGET_SYSROOT" \
    -Xlinker  "-rpath=$CUDA_RUNTIME_DIR" \
    -I"$CUDA_TARGET_DIR/include" \
    -L"$CUDA_TARGET_DIR/lib" \
    -o vectorAdd vectorAdd.cu \
    -lcudart

file vectorAdd
echo "Built: $(pwd)/vectorAdd"
