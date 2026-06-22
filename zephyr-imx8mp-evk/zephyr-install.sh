#!/usr/bin/env bash
#
# Install the cross-compiled Zephyr firmware into the zephyr-m7 extension
# sysroot. avocado-cli runs this after sdk.compile.zephyr finishes.
#
# AVOCADO_BUILD_EXT_SYSROOT: the sysroot of the extension being built. Files
# placed here are merged into the rootfs when the (sysext) extension is
# activated. The Linux imx_rproc driver searches /lib/firmware (which resolves
# to /usr/lib/firmware under usr-merge), so the ELF goes there.
#
set -euo pipefail

if [ -z "${AVOCADO_BUILD_EXT_SYSROOT:-}" ]; then
  echo "[ERROR] AVOCADO_BUILD_EXT_SYSROOT is not set." >&2
  exit 1
fi

# Stable artifact staged by zephyr-compile.sh (decoupled from Zephyr's
# CONFIG_KERNEL_BIN_NAME, which varies per sample).
ELF="zephyr-m7/build/artifacts/zephyr_imx8mp_m7.elf"
if [ ! -f "${ELF}" ]; then
  echo "[ERROR] ${ELF} not found." >&2
  echo "  Run 'avocado sdk compile zephyr' (or 'avocado build') first." >&2
  exit 1
fi

# Must match the firmware name written by the loader unit
# (zephyr-m7/overlay/usr/sbin/zephyr-m7-load.sh).
DEST_DIR="${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/firmware"
DEST_NAME="zephyr_imx8mp_m7.elf"

echo "================================================================"
echo "Installing Zephyr firmware into extension sysroot"
echo "================================================================"
install -D -m 0644 "${ELF}" "${DEST_DIR}/${DEST_NAME}"
echo "Installed ${ELF} -> /usr/lib/firmware/${DEST_NAME}"
echo "================================================================"
