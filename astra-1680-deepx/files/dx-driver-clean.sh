#!/usr/bin/env bash
set -e

echo "============================================"
echo "Cleaning DeepX NPU driver build artifacts"
echo "============================================"

if [ -d "dx_rt_npu_linux_driver" ]; then
    KDIR=""

    # Find KDIR to pass to make clean
    KERNEL_VERSION=""
    if [ -f "${OECORE_TARGET_SYSROOT}/usr/src/kernel/include/config/kernel.release" ]; then
        KERNEL_VERSION=$(cat "${OECORE_TARGET_SYSROOT}/usr/src/kernel/include/config/kernel.release")
    fi
    if [ -z "$KERNEL_VERSION" ]; then
        KERNEL_VERSION=$(ls "${OECORE_TARGET_SYSROOT}/lib/modules/" 2>/dev/null | head -n1 || echo "")
    fi

    if [ -n "$KERNEL_VERSION" ]; then
        KDIR="${OECORE_TARGET_SYSROOT}/usr/lib/modules/${KERNEL_VERSION}/build"
        if [ ! -d "$KDIR" ]; then
            KDIR="${OECORE_TARGET_SYSROOT}/usr/src/kernel"
        fi
    fi

    if [ -n "$KDIR" ] && [ -f "$KDIR/Makefile" ]; then
        make -C dx_rt_npu_linux_driver/modules \
            DEVICE=m1 \
            PCIE=deepx \
            ARCH=${ARCH} \
            CROSS_COMPILE=${CROSS_COMPILE} \
            KERNEL_DIR=${KDIR} \
            clean || true
    else
        echo "WARNING: Kernel dir not found, removing .ko files manually"
        find dx_rt_npu_linux_driver/modules -name "*.ko" -delete || true
    fi
fi

echo "Clean complete!"
