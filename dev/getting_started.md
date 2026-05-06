# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Dev Starter

This guide walks you through booting an Avocado OS development environment on any supported target. The dev reference gives you a minimal runtime with SSH, dev tools, and i2c-tools — ready for you to build on.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

For hardware targets, you will also need:

- Your target device and any required accessories (SD card, USB cable, serial console adapter)
- See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference dev my-project
cd my-project
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference dev --target raspberrypi5 my-project
cd my-project
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

## Build

Build the runtime image:

```bash
avocado build
```

There are no compile steps in this reference — the build assembles the runtime from pre-built packages and extensions.

## Deploy

### QEMU

For QEMU targets, provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

### SD card targets (Raspberry Pi, Seeed reTerminal, NXP, STMicroelectronics)

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device and apply power.

### USB flash targets (OnLogic)

```bash
avocado provision -r dev --profile usb
```

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB disconnect/reconnect prompts during the flash process.

## Verify

Log in as `root` with an empty password.

Confirm the system is running:

```bash
uname -a
systemctl status
```

Test i2c-tools (hardware targets):

```bash
i2cdetect -l        # list I2C buses
i2cdetect -y 1      # scan bus 1 for devices
```

SSH access is enabled by default via the `avocado-ext-sshd-dev` extension.

## Customize

### Add packages to the app extension

Edit `avocado.yaml` to add packages under the `app` extension:

```yaml
  app:
    version: 0.1.0
    packages:
      i2c-tools: '*'
      spi-tools: '*'
      can-utils: '*'
```

### Add application code

Create an `app/` directory with source code, an overlay, and build scripts following the pattern from other references (e.g., `c-gpio`, `python-flask`).

### Add more extensions

Add pre-built extensions from the package feed:

```yaml
    extensions:
      - app
      - config-dev
      - avocado-ext-dev
      - avocado-ext-sshd-dev
      - avocado-ext-docker        # add Docker support
      - avocado-ext-cockpit       # add web-based management UI
      - avocado-bsp-{{ avocado.target.board }}
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
