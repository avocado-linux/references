---
language: C
targets:
  - imx8mp-evk
topics:
  - cross-compilation
  - bootloader
  - secure-boot
---

# Custom U-Boot (HAB + FIT signature) for i.MX 8M Plus EVK

A reference runtime that demonstrates how to cross-compile a custom
`imx-boot` bundle (TF-A BL31 + U-Boot SPL/proper + DDR firmware) from
source using the Avocado SDK and replace the upstream-installed
bootloader on an NXP i.MX 8M Plus EVK.

- Cross-compile NXP's `uboot-imx`, `imx-atf`, and `imx-mkimage` for
  imx8mp inside the SDK container, bundled with NXP's redistributable
  DDR4 firmware.
- Enable `CONFIG_IMX_HAB=y` so the resulting flash.bin is HAB-ready
  (parses CSF blobs, can be signed against the SoC's SRK fuses).
- Enable `CONFIG_FIT_SIGNATURE=y` plus a placeholder /signature node in
  the U-Boot control DTB. After build, `insert-fit-pubkey.sh` runs
  `mkimage -K` to inject your RSA pubkey into the placeholder and
  rebuilds flash.bin — letting you rotate FIT signing keys without
  rebuilding U-Boot itself.
- Use the `runtimes.<n>.packages.<name>.{compile,install}` hook (mirrors
  the extension `packages.<dep>.{compile,install}` form) to drop the
  built `imx-boot` into the runtime build dir, where stone bundles it
  into the os-bundle in place of any upstream artifact.

## Why custom U-Boot?

The upstream Avocado-provided `imx-boot` is unsigned and uses a generic
`/signature` configuration. Two reasons you'd build your own:

1. **HAB closure.** Closing HAB on a production device requires fusing
   the SRK hash and shipping a flash.bin signed against that key. You
   need control over the bootloader binary to attach the right CSF, and
   you typically tie HAB closure to a hardware certification milestone.
2. **FIT image verification.** With `CONFIG_FIT_SIGNATURE=y` and a
   pubkey embedded in the U-Boot DTB, the bootloader will refuse to
   load a kernel/initramfs that wasn't signed with the matching private
   key. The dtsi placeholder lets you ship the same flash.bin to many
   units and rotate the pubkey without a U-Boot rebuild.

See [getting_started.md](getting_started.md) for the build, the
`mkimage -K` post-build flow, and notes on closing HAB.
