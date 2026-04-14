---
language: C
targets:
  - qemux86-64
topics:
  - cross-compilation
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Custom Linux Kernel

A reference runtime that demonstrates how to cross-compile a custom Linux kernel from source using the Avocado SDK and boot it on QEMU. Replaces the default kernel provided by the `avocado-runtime` meta-package with a from-source build of Linux 6.12.69.

- Download, configure, and cross-compile the Linux kernel inside the SDK container
- Handle SDK environment conflicts with the kernel build system (HOSTCC, sysroot, unset userspace flags)
- Apply Avocado-required kernel config options (overlayfs, squashfs, btrfs, systemd, virtio)
- Package the compiled kernel as an RPM for distribution via a private package feed
