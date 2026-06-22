#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "============================================"
echo "Installing DeepX NPU modules into extension"
echo "============================================"

# Get kernel version from the kernel source
KDIR="${OECORE_TARGET_SYSROOT}/usr/src/kernel"

if [ -f "$KDIR/include/config/kernel.release" ]; then
    KERNEL_VERSION=$(cat "$KDIR/include/config/kernel.release")
elif [ -f "$KDIR/include/generated/utsrelease.h" ]; then
    KERNEL_VERSION=$(grep UTS_RELEASE "$KDIR/include/generated/utsrelease.h" | cut -d'"' -f2)
else
    echo "ERROR: Could not determine kernel version from $KDIR"
    exit 1
fi

echo "Kernel version: $KERNEL_VERSION"

RT_KO="dx_rt_npu_linux_driver/modules/rt/dxrt_driver.ko"
PCIE_KO="dx_rt_npu_linux_driver/modules/pci_deepx/dx_dma.ko"

if [ ! -f "$RT_KO" ] || [ ! -f "$PCIE_KO" ]; then
    echo "ERROR: One or more module binaries not found. Run compile step first."
    echo "  Expected: $RT_KO"
    echo "  Expected: $PCIE_KO"
    exit 1
fi

# Install modules into the extension sysroot under usr/lib/modules/.../extra/
# Mirrors the subdirectory layout used by the upstream Makefile's install target.
RT_MODULE_DIR="${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/modules/${KERNEL_VERSION}/extra/rt"
PCIE_MODULE_DIR="${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/modules/${KERNEL_VERSION}/extra/pci_deepx"

install -d "$RT_MODULE_DIR"
install -d "$PCIE_MODULE_DIR"

install -m 0644 "$RT_KO"   "$RT_MODULE_DIR/"
install -m 0644 "$PCIE_KO" "$PCIE_MODULE_DIR/"

echo "Modules installed successfully!"
echo "  $RT_MODULE_DIR/dxrt_driver.ko"
echo "  $PCIE_MODULE_DIR/dx_dma.ko"
