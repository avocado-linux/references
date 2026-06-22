#!/usr/bin/env bash
#
# Cross-compile a Zephyr RTOS firmware image for the i.MX 8M Plus EVK's
# Cortex-M7 co-processor, inside the Avocado SDK container.
#
# This demonstrates the SDK-as-toolchain model: the SDK ships only the
# bare-metal ARM compiler (nativesdk-gcc-arm-none-eabi) plus cmake/ninja/
# dtc/gperf. The Zephyr tree + its version are fetched here, by this
# project, via west -- so nothing in the distro pins a Zephyr version.
# Swap ZEPHYR_REV / the manifest below for mainline Zephyr, a Zephyr LTS,
# or a downstream fork (e.g. Nordic's nRF Connect SDK) without touching the
# distro. The same compiler builds STM32Cube, FreeRTOS, or plain bare-metal
# firmware just as well.
#
# Sample: samples/subsys/ipc/openamp_rsc_table -- the canonical Linux-
# interop sample. It embeds an OpenAMP resource table at the address the
# imx8mp-evk-rpmsg devicetree expects, so the Linux remoteproc driver can
# load it and an rpmsg channel comes up between the A53 (Linux) and the M7.
#
# Output (staged project-relative so zephyr-install.sh / zephyr-clean.sh
# can find / discard it, matching the rzv2n-drpai-yolo reference):
#   zephyr-m7/build/zephyrproject/build/zephyr/zephyr.elf
#
set -euo pipefail

# Pin the Zephyr revision for reproducibility. Bump deliberately. The board
# name and sample path below track Zephyr's hardware-model-v2 layout; adjust
# if you pin an older Zephyr.
ZEPHYR_MANIFEST_URL="https://github.com/zephyrproject-rtos/zephyr"
ZEPHYR_REV="v4.1.0"
ZEPHYR_BOARD="imx8mp_evk/mimx8ml8/m7"
ZEPHYR_SAMPLE="samples/subsys/ipc/openamp_rsc_table"

HOST_SRC="$(pwd)"
BUILD_DIR="${HOST_SRC}/zephyr-m7/build"
WEST_TOPDIR="${BUILD_DIR}/zephyrproject"
VENV_DIR="${BUILD_DIR}/.venv"

echo "================================================================"
echo "Building Zephyr ${ZEPHYR_REV} for ${ZEPHYR_BOARD}"
echo "  sample: ${ZEPHYR_SAMPLE}"
echo "================================================================"

mkdir -p "${BUILD_DIR}"

# ---------------------------------------------------------------------------
# Toolchain: point Zephyr at the SDK's bare-metal ARM GCC (gnuarmemb).
#
# nativesdk-gcc-arm-none-eabi symlinks arm-none-eabi-gcc into the SDK's
# bindir; the real toolchain lives under libexec. Zephyr's gnuarmemb variant
# wants GNUARMEMB_TOOLCHAIN_PATH = the dir that contains bin/arm-none-eabi-*.
# Derive it from the resolved symlink so we don't hardcode the SDK layout.
# ---------------------------------------------------------------------------
ARM_GCC="$(command -v arm-none-eabi-gcc || true)"
if [ -z "${ARM_GCC}" ]; then
  echo "[ERROR] arm-none-eabi-gcc not found on PATH." >&2
  echo "  Ensure nativesdk-gcc-arm-none-eabi is in the SDK (it ships on" >&2
  echo "  cortex-m machines, and is listed under sdk.packages here)." >&2
  exit 1
fi
ARM_GCC_REAL="$(readlink -f "${ARM_GCC}")"
export GNUARMEMB_TOOLCHAIN_PATH="$(dirname "$(dirname "${ARM_GCC_REAL}")")"
export ZEPHYR_TOOLCHAIN_VARIANT="gnuarmemb"
echo "ZEPHYR_TOOLCHAIN_VARIANT=${ZEPHYR_TOOLCHAIN_VARIANT}"
echo "GNUARMEMB_TOOLCHAIN_PATH=${GNUARMEMB_TOOLCHAIN_PATH}"

# The SDK exports an aarch64 userspace cross toolchain (CC/CFLAGS/...). That
# is for target Linux userspace, not bare-metal M7 firmware; clear it so it
# can't leak into Zephyr's CMake/Kconfig. Zephyr drives everything from the
# gnuarmemb variant above.
unset CC CXX CPP LD AR AS NM STRIP OBJCOPY OBJDUMP READELF RANLIB
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS

# ---------------------------------------------------------------------------
# Python env: west + Zephyr's build-script requirements (pyelftools, etc).
# Kept in the build dir so it survives across runs and is discarded by
# zephyr-clean.sh.
# ---------------------------------------------------------------------------
if [ ! -d "${VENV_DIR}" ]; then
  echo "Creating python venv at ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
. "${VENV_DIR}/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet west

# ---------------------------------------------------------------------------
# Fetch Zephyr + modules via west (pinned to ZEPHYR_REV).
# ---------------------------------------------------------------------------
if [ ! -d "${WEST_TOPDIR}/.west" ]; then
  echo "west init -m ${ZEPHYR_MANIFEST_URL} --mr ${ZEPHYR_REV}"
  west init -m "${ZEPHYR_MANIFEST_URL}" --mr "${ZEPHYR_REV}" "${WEST_TOPDIR}"
fi
cd "${WEST_TOPDIR}"
west update --narrow -o=--depth=1
west zephyr-export

# Zephyr's python build dependencies (matches the pinned tree).
pip install --quiet -r zephyr/scripts/requirements.txt

# ---------------------------------------------------------------------------
# Build.
#
# C library: force newlib. Zephyr defaults to picolibc, but Arm's GNU
# toolchain (gnuarmemb) ships no prebuilt picolibc, so Zephyr falls back to
# building picolibc *from source* -- and that source build mis-selects the
# aarch64 machine assembly for our arm (Cortex-M7) target (it assembles
# newlib/libc/machine/aarch64/*.S with the Thumb assembler and dies).
# newlib ships prebuilt in the arm-none-eabi toolchain (CONFIG_NEWLIB_LIBC_-
# SUPPORTED=y), so it links cleanly with no from-source compile.
#
# The upstream-recommended alternative is the official Zephyr SDK (it bundles
# a prebuilt picolibc per arch); adopting it here would mean packaging that
# SDK as a nativesdk recipe -- a deliberate future step, not required for
# this demo.
# ---------------------------------------------------------------------------
echo "Building ${ZEPHYR_SAMPLE} for ${ZEPHYR_BOARD}..."
west build -p always -b "${ZEPHYR_BOARD}" -d "${WEST_TOPDIR}/build" \
  "${WEST_TOPDIR}/zephyr/${ZEPHYR_SAMPLE}" \
  -- -DCONFIG_NEWLIB_LIBC=y

# Zephyr names the final image after CONFIG_KERNEL_BIN_NAME, which samples
# may override (openamp_rsc_table -> zephyr_openamp_rsc_table.elf), so it
# isn't always zephyr.elf. Read the configured name, then stage the artifact
# under a stable path that zephyr-install.sh consumes.
KERNEL_BIN_NAME="$(sed -n 's/^CONFIG_KERNEL_BIN_NAME="\(.*\)"$/\1/p' "${WEST_TOPDIR}/build/zephyr/.config")"
KERNEL_BIN_NAME="${KERNEL_BIN_NAME:-zephyr}"
ELF="${WEST_TOPDIR}/build/zephyr/${KERNEL_BIN_NAME}.elf"
if [ ! -f "${ELF}" ]; then
  echo "[ERROR] expected ${ELF} not produced." >&2
  exit 1
fi

ARTIFACT_DIR="${BUILD_DIR}/artifacts"
mkdir -p "${ARTIFACT_DIR}"
install -m 0644 "${ELF}" "${ARTIFACT_DIR}/zephyr_imx8mp_m7.elf"

echo ""
echo "================================================================"
echo "Zephyr firmware build complete:"
echo "  ${ELF}"
echo "  staged -> ${ARTIFACT_DIR}/zephyr_imx8mp_m7.elf"
file "${ELF}" || true
echo "================================================================"
