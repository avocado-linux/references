#!/bin/sh
#
# Load the Zephyr firmware onto the i.MX8MP Cortex-M7 via the Linux
# remoteproc driver. POSIX sh (BusyBox-safe) for the read-only Avocado
# rootfs. Driven by zephyr-m7-remoteproc.service.
#
set -eu

RPROC=/sys/class/remoteproc/remoteproc0
# Must match the name zephyr-install.sh writes into /usr/lib/firmware.
FW=zephyr_imx8mp_m7.elf

if [ ! -d "${RPROC}" ]; then
  echo "remoteproc0 not present: boot the imx8mp-evk-rpmsg devicetree to" >&2
  echo "enable the Cortex-M7 remoteproc node." >&2
  exit 1
fi

state="$(cat "${RPROC}/state")"
if [ "${state}" = "running" ]; then
  echo "M7 already running; stopping to reload ${FW}"
  echo stop > "${RPROC}/state"
fi

echo "${FW}" > "${RPROC}/firmware"
echo start > "${RPROC}/state"
echo "Started M7 with ${FW} (state: $(cat "${RPROC}/state"))"
