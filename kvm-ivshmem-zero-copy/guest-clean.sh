#!/usr/bin/env bash
set -euo pipefail
: "${AVOCADO_BUILD_DIR:?AVOCADO_BUILD_DIR not set}"
rm -rf "${AVOCADO_BUILD_DIR}/root" "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz"
