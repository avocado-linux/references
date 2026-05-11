#!/usr/bin/env bash
#
# Clean the imx-boot build directory.
#
# Removes $AVOCADO_BUILD_DIR (uboot-imx, imx-atf, imx-mkimage,
# firmware-imx, intermediate flash.bin). Cached upstream tarballs under
# .downloads/ on the host are left in place so re-runs don't re-fetch
# from the network.
#
set -e

if [ -z "${AVOCADO_BUILD_DIR:-}" ]; then
  echo "[ERROR] AVOCADO_BUILD_DIR is not set." >&2
  exit 1
fi

if [ ! -d "${AVOCADO_BUILD_DIR}" ]; then
  echo "Build directory ${AVOCADO_BUILD_DIR} does not exist, nothing to clean."
  exit 0
fi

echo "================================================================"
echo "Cleaning imx-boot build directory: ${AVOCADO_BUILD_DIR}"
echo "================================================================"

rm -rf "${AVOCADO_BUILD_DIR}"

echo "Build directory cleaned."
