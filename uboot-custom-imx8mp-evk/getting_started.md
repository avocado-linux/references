# Getting Started — Custom U-Boot for i.MX 8M Plus EVK

This guide walks you through cross-compiling a custom imx-boot
bundle from source and flashing it onto an i.MX 8M Plus EVK. The
reference matches the pins nxp-imx/meta-imx ships at
`scarthgap-6.6.36-2.1.0` (uboot-imx `lf_v2024.04`, imx-atf `lf_v2.10`,
imx-mkimage `lf-6.6.36_2.1.0`, firmware-imx 8.25-27879f8) with HAB and
FIT signature support enabled, and replaces the bootloader Avocado
would otherwise pull in.

## Prerequisites

- Linux host (Ubuntu 22.04+, Fedora 39+) — or macOS with Docker Desktop.
- [Docker](https://www.docker.com/products/docker-desktop/) running.
- Avocado CLI: see [docs.peridio.com](https://docs.peridio.com).
- An i.MX 8M Plus EVK in serial-download (USB-OTG) mode for flashing
  via `uuu-emmc`.

## Initialize

```bash
avocado init --reference uboot-custom-imx8mp-evk uboot-imx8mp-evk
cd uboot-imx8mp-evk
```

## Install

```bash
avocado install -f
```

This pulls the Avocado SDK container and installs `nativesdk-bc`,
`nativesdk-bison`, `nativesdk-flex`, `nativesdk-openssl`,
`nativesdk-dtc`, `nativesdk-util-linux` — the build deps needed by
U-Boot, TF-A, and imx-mkimage.

## Build

```bash
avocado build
```

The build runs `uboot-compile.sh` inside the SDK container, which:

1. Saves `CROSS_COMPILE` / `ARCH` from the SDK env, then unsets the
   userspace `CC`, `CFLAGS`, `LDFLAGS` exports that fight the U-Boot
   and TF-A build systems (same trick the Linux kernel reference uses).
2. Clones `uboot-imx` (branch `lf_v2024.04`, SRCREV
   `de16f4f1`), `imx-atf` (branch `lf_v2.10`, SRCREV `28affcae`),
   `imx-mkimage` (branch `lf-6.6.36_2.1.0`, SRCREV `4622115c`), and
   downloads `firmware-imx-8.25-27879f8.bin` from NXP's mirror — the
   exact pins meta-imx ships at scarthgap-6.6.36-2.1.0.
3. Appends `patches/avocado.cfg` + `patches/env-mmc.cfg` onto
   `imx8mp_evk_defconfig`, and adds `#include
   "avocado-fit-signature.dtsi"` to `imx8mp-evk-u-boot.dtsi` so the
   control DTB carries a placeholder /signature node.
4. Builds TF-A BL31, builds U-Boot, generates a redundant `uboot.env`
   from `patches/avocado-imx8mp-evk.txt`.
5. Stages the binaries into `iMX8M/` and runs
   `make SOC=iMX8MP flash_evk` to produce `flash.bin` (== `imx-boot`).

`uboot-install.sh` then drops `flash.bin` and `uboot.env` into
`$AVOCADO_RUNTIME_BUILD_DIR`, so the stone bundle assembled by
`avocado build` carries our bootloader.

You can also rebuild only the bootloader without re-assembling the
runtime:

```bash
avocado sdk compile uboot
```

## Inject a FIT signing pubkey (the "replace later" workflow)

The bootloader you just built has `/signature/key-rt-prod` as a
placeholder — empty `rsa,modulus` etc. To actually have it verify FIT
images, populate that node with your dev pubkey:

```bash
avocado sdk run -E -- bash insert-fit-pubkey.sh
avocado build
```

`insert-fit-pubkey.sh`:

1. Generates `keys/dev.key` + `keys/dev.crt` if missing.
2. Builds a throwaway FIT image referencing `key-name-hint = "dev"`.
3. Runs `mkimage -F -K …` so mkimage extracts the pubkey from
   `keys/dev.key` and patches it into the placeholder /signature node
   *in the already-built U-Boot DTB* — no full U-Boot rebuild.
4. Re-runs `imx-mkimage` to fold the patched DTB back into a fresh
   `flash.bin`.

Re-running `avocado build` then re-stages the updated bootloader in the
runtime build dir.

To rotate the key, drop a new `keys/dev.key` (or change `KEY_NAME` in
the script) and re-run `insert-fit-pubkey.sh` + `avocado build`. The
core bootloader binary doesn't change — only the pubkey block in the
control DTB.

To sign your real FIT images (kernel + dtb + initramfs) for this
bootloader to accept:

```bash
mkimage -F -k keys -r <fit-image.itb>
```

## Provision the EVK

Put the EVK in serial-download mode (set boot DIPs SW4 to
`0011 0010 0010 1000`, the documented serial-download position — see
the EVK user manual; do not press an arbitrary BOOT+RESET combo) and
plug a USB-C cable into the OTG port:

```bash
avocado provision -r dev --profile uuu-emmc
```

uuu hands `flash.bin` to the boot ROM via SDPS, then writes the OS
bundle (rootfs / initramfs / kernel) to eMMC. Reset the board with
DIPs back to eMMC boot — your custom HAB-ready U-Boot runs first.

## Closing HAB (production-only)

The build leaves HAB *open* — i.e., this flash.bin will boot on any
imx8mp without signature checks. Closing HAB is a one-way fuse blow:
**do not do this on a dev board you want to recover.**

The full procedure is documented in NXP's
[i.MX Secure Boot on AHAB and HAB CST](https://www.nxp.com/docs/en/application-note/AN12056.pdf)
guide. Sketch:

1. Generate SRK / CSF / IMG keys with NXP's CST.
2. Run `cst -i csf-spl.txt` and `cst -i csf-uboot.txt` against the
   `flash.bin` produced by this reference. Use the `imx_log` block at
   the start of the build output to find the load addresses CST needs.
3. Append the resulting CSF blobs to `flash.bin` at the offsets the
   first stage reports.
4. Verify with `hab_status` from the U-Boot prompt — it should report
   "No HAB Events Found!" before you close.
5. Blow the SRK_HASH fuse via `fuse prog`. Once closed, only flash.bin
   binaries signed by your SRK chain will boot.

## Customize

### Different NXP release line

Bump the branch + SRCREV pairs at the top of `uboot-compile.sh` to
match the meta-imx tag for the release line you want. The canonical
source is the matching `recipes-bsp/{imx-atf,u-boot,imx-mkimage}/*.bb`
and `recipes-bsp/firmware-imx/firmware-imx-*.inc` in
[nxp-imx/meta-imx](https://github.com/nxp-imx/meta-imx) — open the
files at the tag for your release line and copy the
`SRCBRANCH` / `SRCREV` / firmware-imx PV + IMX_SRCREV_ABBREV values
verbatim.

### Different i.MX 8M variant

Swap `UBOOT_DEFCONFIG`, `ATF_PLATFORM`, `MKIMAGE_SOC`, and
`MKIMAGE_TARGET` in `uboot-compile.sh`. Check
`imx-mkimage/iMX8M/soc.mak` for the available targets and the staging
filenames each one expects.

### Customize the boot env

Edit `patches/avocado-imx8mp-evk.txt`. The format is mkenvimage(1) —
each line is a `key=value` U-Boot env entry.

### Different supported_targets

This reference is hard-coded to imx8mp-evk because of the imx-mkimage
target name. To support multiple boards, switch on
`{{ avocado.target.board }}` in `avocado.yaml` and gate the
`uboot-compile.sh` choices off `$AVOCADO_TARGET`.
