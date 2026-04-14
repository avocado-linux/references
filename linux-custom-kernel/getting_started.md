# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Custom Linux Kernel

This guide walks you through cross-compiling a custom Linux kernel from source and booting it on Avocado OS in QEMU. The reference builds Linux 6.12.69 for qemux86-64, replacing the default kernel from the `avocado-runtime` package.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference linux-custom-kernel linux-custom-kernel
cd linux-custom-kernel
```

## Install

Install the SDK toolchain and build dependencies:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-bc` (for kernel `timeconst.h` generation) and `nativesdk-libelf1` (for `objtool`).

## Build

Build the kernel and assemble the runtime image:

```bash
avocado build
```

The build step runs `kernel-compile.sh` inside the SDK container, which:

1. Downloads the Linux 6.12.69 source tarball from kernel.org (cached for subsequent builds)
2. Extracts into `$AVOCADO_BUILD_DIR` inside the container's case-sensitive filesystem
3. Saves `CROSS_COMPILE` and `ARCH` from the SDK, then unsets conflicting userspace variables (`CC`, `CFLAGS`, `LDFLAGS`, etc.)
4. Configures with `x86_64_defconfig` plus Avocado-required options (overlayfs, squashfs, btrfs, systemd cgroups, virtio drivers, TPM)
5. Cross-compiles `bzImage` using the SDK toolchain

Then `kernel-install.sh` copies the resulting `bzImage` into `$AVOCADO_RUNTIME_BUILD_DIR` where the runtime assembly picks it up.

You can also compile the kernel independently:

```bash
avocado sdk compile kernel
```

## Deploy

### QEMU

Provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

## Verify

Log in as `root` with an empty password. Confirm the custom kernel is running:

```bash
uname -r
```

You should see:

```
6.12.69
```

## Customize

### Change the kernel version

Edit `kernel-compile.sh` to update the version and URL:

```bash
KERNEL_SRC="linux-6.13.0"
KERNEL_VERSION="6.13.0"
KERNEL_TARBALL="${KERNEL_SRC}.tar.xz"
KERNEL_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/${KERNEL_TARBALL}"
```

Also update the version in `avocado.yaml` under `sdk.compile.kernel.package.version` and `kernel-package-install.sh`.

### Add or remove kernel config options

Edit `kernel-compile.sh` to add `scripts/config` calls after the base defconfig and before `make olddefconfig`:

```bash
# Enable a new driver
scripts/config --enable CONFIG_MY_DRIVER

# Disable an unwanted feature
scripts/config --disable CONFIG_SOME_FEATURE
```

### Use a custom defconfig

Replace the `x86_64_defconfig` line with your own:

```bash
cp /path/to/my_defconfig arch/x86/configs/my_defconfig
make "${MAKE_ARGS[@]}" my_defconfig
```

### Package as an RPM

Compile and package the kernel for distribution via a private package feed:

```bash
avocado sdk compile kernel
avocado sdk package kernel --out-dir ./rpms
```

The resulting RPM can then be referenced in `avocado.yaml` via `kernel.package` instead of `kernel.compile`:

```yaml
runtimes:
  dev:
    kernel:
      package: kernel-image-custom
      version: '6.12.69'
```

### Adapt for a different target

| What to change | Why |
|---|---|
| `ARCH` and defconfig | Each architecture has its own defconfig and `ARCH` value (`arm64`, `arm`, `x86`, `riscv`) |
| Kernel image name | ARM64 produces `Image`, ARM produces `zImage`, x86 produces `bzImage` |
| Root device driver | Match the storage controller on your hardware (eMMC, NVMe, SATA, virtio-blk) |
| `HOSTCC` strategy | For same-arch builds the cross-compiler works; for cross-arch builds install `nativesdk-gcc` |

### Rebuild after changes

After any change, rebuild:

```bash
avocado build
avocado provision -r dev
```
