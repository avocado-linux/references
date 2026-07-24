# Getting Started with Zephyr on the i.MX 8M Plus EVK Cortex-M7

This guide builds a Zephyr RTOS firmware for the i.MX8MP's Cortex-M7 co-processor inside the Avocado SDK and runs it alongside Linux, with the two cores talking over rpmsg (OpenAMP).

## Prerequisites

- **Hardware:** NXP i.MX 8M Plus EVK (`imx8mp-evk`) and boot media (SD card) for first-time provisioning.
- **Host:** the [Avocado CLI](https://docs.peridio.com) and Docker (the SDK runs in a container).
- **Network:** the build fetches Zephyr sources via `west`, so the SDK container needs network access (already set with `--network=host` in `avocado.yaml`).
- **U-Boot access:** a serial console to the EVK so you can set the boot devicetree (see Deploy).

## Initialize

```bash
git clone https://github.com/avocado-linux/references.git
cd references/zephyr-imx8mp-evk
```

`default_target` is `imx8mp-evk`, so no `--target` flag is needed.

## Install

```bash
avocado install
```

This resolves the runtime plus the SDK toolchain, including `nativesdk-gcc-arm-none-eabi` (the bare-metal ARM compiler used to build the M7 firmware).

## Build

```bash
avocado build
```

For this reference the build step, inside the SDK:

1. `west init/update`s Zephyr at the revision pinned in `zephyr-compile.sh`.
2. Cross-compiles the `samples/subsys/ipc/openamp_rsc_table` sample for `imx8mp_evk/mimx8ml8/m7` with the `gnuarmemb` toolchain → `zephyr.elf`.
3. Installs it into the `zephyr-m7` extension at `/usr/lib/firmware/zephyr_imx8mp_m7.elf`.

To iterate on just the firmware: `avocado sdk compile zephyr` (and `avocado sdk clean zephyr` to wipe it).

## Deploy

**First time (provision the board):**

```bash
avocado provision -r dev
```

Write the image to your media and boot the EVK.

**Boot the rpmsg devicetree (required for the M7 to come up).** By default the EVK boots `imx8mp-evk.dtb`, which has no M7 node. From the U-Boot console, point `fdtfile` at the rpmsg devicetree shipped by the BSP:

```
setenv fdtfile imx8mp-evk-rpmsg.dtb
saveenv
```

Without this, `/sys/class/remoteproc/remoteproc0` won't exist and the loader service no-ops by design.

**Iterative updates (already provisioned + reachable):**

```bash
avocado deploy -r dev -d <board-ip>
```

## Verify

After boot, confirm the firmware is present and the M7 is running:

```bash
ls -l /usr/lib/firmware/zephyr_imx8mp_m7.elf
systemctl status zephyr-m7-remoteproc.service
cat /sys/class/remoteproc/remoteproc0/state    # -> running
```

Confirm the A53 ↔ M7 rpmsg link:

```bash
ls /sys/bus/rpmsg/devices                       # rpmsg endpoint(s)
dmesg | grep -iE 'remoteproc|rpmsg|virtio'
```

The `openamp_rsc_table` sample echoes messages back over rpmsg; see the Zephyr sample docs for the matching Linux-side `rpmsg` test.

## Customize

Edit the pins at the top of `zephyr-compile.sh`:

- **`ZEPHYR_MANIFEST_URL` / `ZEPHYR_REV`** — the manifest repo + revision. Swap for a fork (e.g. Nordic's nRF Connect SDK) or a different tag. Nothing in the distro is pinned to a Zephyr release.
- **`ZEPHYR_BOARD` / `ZEPHYR_SAMPLE`** — the board name and sample path track Zephyr's hardware-model-v2 layout; adjust if you pin an older Zephyr (e.g. board named `mimx8mp_evk_m7`).

The same bare-metal toolchain builds FreeRTOS, STM32Cube, or plain bare-metal firmware just as well — point the compile hook at your source and rebuild.
