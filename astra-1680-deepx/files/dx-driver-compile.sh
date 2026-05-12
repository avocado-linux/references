#!/usr/bin/env bash
set -e

echo "============================================"
echo "Building DeepX NPU Linux driver"
echo "============================================"

DRIVER_TAG="v2.4.1"
PATCH_FILE="$(pwd)/files/0001-dx_dma-fix-sleeping-in-atomic-BUG-in-dw_edma_free_de.patch"

# Clone the driver repository with submodules if not already present
if [ ! -d "dx_rt_npu_linux_driver" ]; then
    echo "Cloning dx_rt_npu_linux_driver repository..."
    git clone --recurse-submodules https://github.com/DEEPX-AI/dx_rt_npu_linux_driver.git
fi

echo "Checking out $DRIVER_TAG..."
git -C dx_rt_npu_linux_driver fetch --tags
git -C dx_rt_npu_linux_driver checkout "$DRIVER_TAG"
git -C dx_rt_npu_linux_driver submodule update --init --recursive

# Apply patch if not already applied
if git -C dx_rt_npu_linux_driver apply --check --reverse "$PATCH_FILE" 2>/dev/null; then
    echo "Patch already applied, skipping."
elif git -C dx_rt_npu_linux_driver apply --check "$PATCH_FILE" 2>/dev/null; then
    echo "Applying patch: $(basename "$PATCH_FILE")..."
    git -C dx_rt_npu_linux_driver apply "$PATCH_FILE"
    echo "Patch applied successfully."
else
    echo "ERROR: Patch does not apply cleanly to $DRIVER_TAG"
    exit 1
fi

# Find the kernel version
KERNEL_VERSION=""

if [ -f "${OECORE_TARGET_SYSROOT}/usr/src/kernel/include/config/kernel.release" ]; then
    KERNEL_VERSION=$(cat "${OECORE_TARGET_SYSROOT}/usr/src/kernel/include/config/kernel.release")
fi

if [ -z "$KERNEL_VERSION" ]; then
    KERNEL_VERSION=$(ls "${OECORE_TARGET_SYSROOT}/lib/modules/" 2>/dev/null | head -n1 || echo "")
fi

if [ -z "$KERNEL_VERSION" ]; then
    echo "ERROR: Could not determine kernel version"
    exit 1
fi

echo "Kernel version: $KERNEL_VERSION"

# The kernel build directory
KDIR="${OECORE_TARGET_SYSROOT}/usr/lib/modules/${KERNEL_VERSION}/build"

if [ ! -d "$KDIR" ]; then
    KDIR="${OECORE_TARGET_SYSROOT}/usr/src/kernel"
fi

echo "Kernel build dir: $KDIR"

if [ ! -f "$KDIR/Makefile" ]; then
    echo "ERROR: No Makefile found in $KDIR"
    echo "Make sure kernel-devsrc package is installed"
    exit 1
fi

echo "Cross compiler prefix: $CROSS_COMPILE"
echo "Architecture: $ARCH"

# The kernel-devsrc package includes script sources but not compiled host binaries.
# We need to build them for the SDK host using 'modules_prepare'.
# These are HOST binaries (run on SDK host), so we use HOSTCC (not CROSS_COMPILE).
if [ ! -x "$KDIR/scripts/mod/modpost" ]; then
    echo "Preparing kernel for module compilation (modules_prepare)..."

    HOST_GCC=""
    HOST_GXX=""
    SDK_HOST_PREFIX="${AVOCADO_SDK_ARCH:-x86_64}-avocadosdk-linux"

    if [ -n "$OECORE_NATIVE_SYSROOT" ]; then
        if [ -x "$OECORE_NATIVE_SYSROOT/usr/bin/${SDK_HOST_PREFIX}-gcc" ]; then
            HOST_GCC="$OECORE_NATIVE_SYSROOT/usr/bin/${SDK_HOST_PREFIX}-gcc"
            HOST_GXX="$OECORE_NATIVE_SYSROOT/usr/bin/${SDK_HOST_PREFIX}-g++"
        elif [ -x "$OECORE_NATIVE_SYSROOT/usr/bin/gcc" ]; then
            HOST_GCC="$OECORE_NATIVE_SYSROOT/usr/bin/gcc"
            HOST_GXX="$OECORE_NATIVE_SYSROOT/usr/bin/g++"
        fi
    fi

    if [ -z "$HOST_GCC" ]; then
        if command -v ${SDK_HOST_PREFIX}-gcc &>/dev/null; then
            HOST_GCC="${SDK_HOST_PREFIX}-gcc"
            HOST_GXX="${SDK_HOST_PREFIX}-g++"
        elif command -v gcc &>/dev/null; then
            HOST_GCC="gcc"
            HOST_GXX="g++"
        else
            echo "ERROR: No host gcc found. Need nativesdk-gcc or system gcc."
            echo "OECORE_NATIVE_SYSROOT=$OECORE_NATIVE_SYSROOT"
            echo "SDK_HOST_PREFIX=$SDK_HOST_PREFIX"
            exit 1
        fi
    fi

    echo "Using host compiler: $HOST_GCC"

    make -C "${KDIR}" \
        ARCH=${ARCH} \
        CROSS_COMPILE=${CROSS_COMPILE} \
        HOSTCC="${HOSTCC:-$HOST_GCC}" \
        HOSTCXX="${HOSTCXX:-$HOST_GXX}" \
        modules_prepare
fi

# Build the DeepX RT NPU modules
# Produces: modules/rt/dxrt_driver.ko and modules/pci_deepx/dx_dma.ko
echo "Building DeepX RT NPU modules..."
make -C dx_rt_npu_linux_driver/modules \
    DEVICE=m1 \
    PCIE=deepx \
    ARCH=${ARCH} \
    CROSS_COMPILE=${CROSS_COMPILE} \
    KERNEL_DIR=${KDIR}

echo "Build complete!"
echo "Modules built:"
ls -lh dx_rt_npu_linux_driver/modules/rt/dxrt_driver.ko
ls -lh dx_rt_npu_linux_driver/modules/pci_deepx/dx_dma.ko
