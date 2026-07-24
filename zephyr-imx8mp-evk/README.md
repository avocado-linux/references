---
language: C
targets:
  - imx8mp-evk
topics:
  - zephyr
  - rtos
  - cortex-m7
  - rpmsg
  - cross-compilation
---

# Zephyr on the i.MX 8M Plus EVK Cortex-M7

This reference builds a **Zephyr RTOS firmware** for the i.MX8MP's **Cortex-M7**
co-processor entirely inside the **Avocado SDK**, with `avocado build`, and runs
it alongside Linux so the two cores talk over **rpmsg** (OpenAMP).

It demonstrates the SDK-as-toolchain model: the distro ships only a bare-metal
ARM compiler and the usual build tools (`gcc-arm-none-eabi`, `cmake`, `ninja`,
`dtc`, `gperf`). The Zephyr source — and its *version* — are fetched by this
project via `west`, so nothing in the distro is pinned to one Zephyr release.
Point [`zephyr-compile.sh`](zephyr-compile.sh) at mainline Zephyr, a Zephyr LTS,
or a downstream fork (e.g. Nordic's nRF Connect SDK) and rebuild — no distro
change. The same toolchain builds STM32Cube, FreeRTOS, or plain bare-metal
firmware just as well.

## How it works

| Stage | File | What happens |
|---|---|---|
| compile | [`zephyr-compile.sh`](zephyr-compile.sh) | In the SDK: `west init/update` Zephyr @ a pinned rev, build `samples/subsys/ipc/openamp_rsc_table` for `imx8mp_evk/mimx8ml8/m7` with the `gnuarmemb` toolchain → `zephyr.elf`. |
| install | [`zephyr-install.sh`](zephyr-install.sh) | Copies `zephyr.elf` into the `zephyr-m7` extension at `/usr/lib/firmware/zephyr_imx8mp_m7.elf`. |
| load | [`zephyr-m7/overlay/usr/sbin/zephyr-m7-load.sh`](zephyr-m7/overlay/usr/sbin/zephyr-m7-load.sh) + the `zephyr-m7-remoteproc.service` unit | At boot, writes the firmware name to remoteproc and starts the M7. |

The `openamp_rsc_table` sample embeds an OpenAMP resource table at the address
the `imx8mp-evk-rpmsg` devicetree expects, so the Linux `imx_rproc` driver loads
it and an rpmsg channel comes up between the A53 (Linux) and the M7.

## Build

```sh
avocado build
```

That runs the compile + install above and assembles the runtime. (To iterate on
just the firmware: `avocado sdk compile zephyr`; to wipe it: `avocado sdk clean zephyr`.)

## Run on hardware

1. **Boot the rpmsg devicetree.** By default the EVK boots `imx8mp-evk.dtb`,
   which has *no* M7 node. The Cortex-M7 remoteproc node + reserved memory live
   in **`imx8mp-evk-rpmsg.dtb`** (shipped by the BSP). Set the boot `fdtfile`
   to it (U-Boot env), e.g.:
   ```
   setenv fdtfile imx8mp-evk-rpmsg.dtb
   saveenv
   ```
   Without this, `/sys/class/remoteproc/remoteproc0` won't exist and the loader
   service no-ops by design (`ConditionPathExists`).

2. **Confirm the firmware is present and the M7 started:**
   ```sh
   ls -l /usr/lib/firmware/zephyr_imx8mp_m7.elf
   systemctl status zephyr-m7-remoteproc.service
   cat /sys/class/remoteproc/remoteproc0/state          # -> running
   ```

3. **Confirm the A53 <-> M7 rpmsg link:**
   ```sh
   ls /sys/bus/rpmsg/devices                            # rpmsg endpoint(s)
   dmesg | grep -i -E 'remoteproc|rpmsg|virtio'
   ```
   The `openamp_rsc_table` sample echoes messages back over rpmsg; see the
   Zephyr sample docs for the matching Linux-side `rpmsg` test.

## Customizing the Zephyr version / app

Edit the pins at the top of [`zephyr-compile.sh`](zephyr-compile.sh):

- `ZEPHYR_MANIFEST_URL` / `ZEPHYR_REV` — the manifest repo + revision. Swap for
  a fork or a different tag. The board name and sample path track Zephyr's
  hardware-model-v2 layout; adjust `ZEPHYR_BOARD` / `ZEPHYR_SAMPLE` if you pin
  an older Zephyr where the board was named `mimx8mp_evk_m7`.

## C library: newlib, not picolibc

The build forces `CONFIG_NEWLIB_LIBC=y`. Zephyr defaults to **picolibc**, but
Arm's GNU toolchain (`gnuarmemb`) ships no prebuilt picolibc, so Zephyr would
build it *from source* — and that source build mis-selects the `aarch64`
machine assembly for our arm/Cortex-M7 target and fails. **newlib** ships
prebuilt in the `arm-none-eabi` toolchain, so it links cleanly. The
upstream-recommended alternative is the official **Zephyr SDK** (it bundles a
prebuilt picolibc per arch); adopting it would mean packaging that SDK as a
`nativesdk` recipe — a deliberate future step, not needed for this demo.

## Requirements

- The SDK must contain `nativesdk-gcc-arm-none-eabi` (the bare-metal ARM
  compiler). On `imx8mp-evk` this is pulled in automatically by the `cortex-m`
  `MACHINE_FEATURE`; it is also listed under `sdk.packages` here so the project
  is self-contained.
- `west update` fetches over the network, so the compile step runs the SDK
  container with `--network=host` (set in `avocado.yaml`).
