#!/usr/bin/env bash
#
# Install the cross-compiled imx-boot artifact into the runtime build
# directory.
#
# AVOCADO_RUNTIME_BUILD_DIR: set by avocado-cli (the
# `runtimes.<n>.packages.uboot.{compile,install}` hook), points to
#   $AVOCADO_PREFIX/runtimes/<runtime_name>/
#
# Stone treats this dir as an input directory when bundling the OS, so
# dropping `imx-boot` here makes our flash.bin land in the os-bundle.aos
# instead of any upstream-provided imx-boot.
#
set -euo pipefail

if [ -z "${AVOCADO_BUILD_DIR:-}" ]; then
  echo "[ERROR] AVOCADO_BUILD_DIR is not set." >&2
  exit 1
fi
if [ -z "${AVOCADO_RUNTIME_BUILD_DIR:-}" ]; then
  echo "[ERROR] AVOCADO_RUNTIME_BUILD_DIR is not set." >&2
  exit 1
fi

FLASH_BIN="${AVOCADO_BUILD_DIR}/flash.bin"
UBOOT_ENV="${AVOCADO_BUILD_DIR}/uboot.env"

if [ ! -f "${FLASH_BIN}" ]; then
  echo "[ERROR] flash.bin not found at ${FLASH_BIN}." >&2
  echo "  Run 'avocado sdk compile uboot' first." >&2
  exit 1
fi

mkdir -p "${AVOCADO_RUNTIME_BUILD_DIR}"

echo "================================================================"
echo "Installing imx-boot into runtime build directory"
echo "================================================================"

# stone-imx8mp-evk.json's rootdisk references this image as `imx-boot`.
echo "Copying flash.bin -> ${AVOCADO_RUNTIME_BUILD_DIR}/imx-boot"
cp -f "${FLASH_BIN}" "${AVOCADO_RUNTIME_BUILD_DIR}/imx-boot"

# Same manifest references `uboot.env` for the redundant uboot-env
# partition. The on-device fw_env.config points at this on MMC.
if [ -f "${UBOOT_ENV}" ]; then
  echo "Copying uboot.env -> ${AVOCADO_RUNTIME_BUILD_DIR}/uboot.env"
  cp -f "${UBOOT_ENV}" "${AVOCADO_RUNTIME_BUILD_DIR}/uboot.env"
fi

echo ""
echo "imx-boot installed successfully."
echo "================================================================"
