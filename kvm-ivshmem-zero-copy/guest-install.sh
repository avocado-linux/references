#!/usr/bin/env bash
# Stage the guest payload into the vmm extension sysroot: the initramfs
# guest-compile.sh built, and the kernel the guests boot.
#
# Runs inside the SDK container after guest-compile.sh. The launcher, the units
# and the shared ivshmem settings are static files and come in via `overlay:`.
set -euo pipefail

: "${AVOCADO_BUILD_DIR:?AVOCADO_BUILD_DIR not set}"
: "${AVOCADO_BUILD_EXT_SYSROOT:?AVOCADO_BUILD_EXT_SYSROOT not set}"
: "${AVOCADO_PREFIX:?AVOCADO_PREFIX not set}"

# The guest's shared-memory driver, from the extension sysroot where the
# kernel-module-avocado-shm package put it. Built by Yocto against each kernel
# (see meta-avocado-qcom/recipes-kernel/avocado-shm) rather than through
# sdk.compile, because there is only one kernel-devsrc in this feed and it is
# the stock kernel -- a module built against it carries the wrong vermagic for
# the RT kernel these guests actually run.
#
# It goes in the initramfs root, not into /lib/modules: shmdemo loads it with
# finit_module("/avocado-shm.ko") because the initramfs holds one binary and
# that binary is init, so there is no shell to insmod from.
shm_ko=$(find "${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/modules" -name 'avocado-shm.ko*' 2>/dev/null | head -1)
if [ -n "$shm_ko" ]; then
    case "$shm_ko" in
        *.ko.xz|*.ko.gz|*.ko.zst)
            echo "ERROR: $shm_ko is compressed; finit_module needs it uncompressed" >&2
            exit 1 ;;
    esac
    echo "Adding guest module: $shm_ko"
    install -m 0644 "$shm_ko" "${AVOCADO_BUILD_DIR}/root/avocado-shm.ko"
    # Re-pack. guest-compile.sh already packed the cpio at the end of the
    # compile step, so adding a file to the root afterwards would otherwise
    # change nothing -- the module has to go into the archive, and the archive
    # is built before this script runs.
    ( cd "${AVOCADO_BUILD_DIR}/root" \
        && find . -print0 | cpio --null --create --format=newc --quiet ) \
        | gzip -9 > "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz"
    echo "Re-packed initramfs with the module: $(stat -c %s "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz") bytes"
else
    echo "WARNING: no avocado-shm.ko in the extension sysroot -- the guest will" >&2
    echo "         fall back to the uncached ivshmem BAR path." >&2
fi

dest="${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/avocado-vm"
install -d "$dest"

install -m 0644 "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz" \
    "$dest/guest-initramfs.cpio.gz"

# The guest kernel, staged as a plain file in the extension.
#
# NOT read from /boot at runtime, which is what launch-vm used to do: on this
# platform the kernel is not in the rootfs image at all -- it lives in the ESP
# inside a UKI -- so /boot is empty on the device and every VM failed with
# "no guest kernel at /boot/Image-<kver>".
#
# Taken from AVOCADO_KERNEL_IMAGE, which avocado-cli sets from the lockfile pin
# -- the same value and the same authority the platform build hook uses to
# decide which kernel goes into the UKI, so host and guest cannot disagree.
#
# Not globbed. Both $AVOCADO_PREFIX/kernel and $AVOCADO_PREFIX/rootfs/boot keep
# an entry per kernel version ever installed, so once a project has resolved
# more than one -- switching this project between the stock and RT pins does
# exactly that -- any glob over either is ambiguous and `head -1` silently
# prefers the alphabetically first, which for 6.18.37 vs 6.18.37-rt is stock.
#
# AVOCADO_KERNEL_IMAGE is exported to extension install scripts only by a CLI
# that carries that change; 1.0.0-rc.3 does not, and the script then aborted
# with "AVOCADO_KERNEL_IMAGE not set". So fall back to the rootfs sysroot's
# /boot, which `avocado install` populates with exactly the pinned kernel --
# unlike $AVOCADO_PREFIX/kernel, which accumulates a directory per kernel ever
# installed. Assert the count rather than head -1 a guess: on a feed carrying
# both a stock and an RT kernel, picking the wrong one silently gives the
# guests a kernel whose modules do not match.
kernel_image="${AVOCADO_KERNEL_IMAGE:-}"
kernel_version="${AVOCADO_KERNEL_VERSION:-}"
if [ -z "$kernel_image" ]; then
    set -- "$AVOCADO_PREFIX"/rootfs/boot/Image-*
    if [ ! -e "$1" ] || [ "$#" -ne 1 ]; then
        echo "[ERROR] AVOCADO_KERNEL_IMAGE unset and $AVOCADO_PREFIX/rootfs/boot" >&2
        echo "        holds $# kernels, not 1: $*" >&2
        echo "        Run 'avocado install', or use a CLI that exports the pin." >&2
        exit 1
    fi
    kernel_image="$1"
    kernel_version=$(basename "$kernel_image" | sed 's/^Image-//')
    echo "AVOCADO_KERNEL_IMAGE unset; using the rootfs sysroot's $kernel_version"
fi
[ -f "$kernel_image" ] || {
    echo "[ERROR] pinned kernel $kernel_image does not exist" >&2
    exit 1
}
install -m 0644 "$kernel_image" "$dest/guest-kernel"

# Recorded so the launcher can report which kernel the guests boot, and so a
# stale extension is obvious on the device.
printf '%s\n' "${kernel_version:-unknown}" > "$dest/guest-kernel.version"

echo "Installed guest payload into the vmm extension:"
echo "  initramfs: $(stat -c %s "$dest/guest-initramfs.cpio.gz") bytes"
echo "  kernel:    ${kernel_version:-unknown} ($(stat -c %s "$dest/guest-kernel") bytes)"
