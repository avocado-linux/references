# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with WebKit UI

This guide walks you through booting an Avocado OS environment with the Cog WebKit kiosk browser on display-capable hardware. Use it as a base for embedded web UIs or for display bring-up and testing.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A supported target with a display:
  - Raspberry Pi 5 or 4 with HDMI display
  - Seeed reTerminal or reTerminal DM (built-in display)
  - Advantech ICAM-540 with display
  - NVIDIA Jetson Orin Nano or AGX Orin with HDMI display
- SD card or USB cable for provisioning

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference webkit-ui --target raspberrypi5 webkit-ui
cd webkit-ui
```

Replace `raspberrypi5` with your target (e.g., `jetson-orin-nano-devkit`, `reterminal`, `icam-540`).

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

There are no compile steps — the build assembles the runtime from pre-built packages and extensions.

## Deploy

### SD card targets (Raspberry Pi, Seeed reTerminal)

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device, connect a display, and apply power.

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB disconnect/reconnect prompts during the flash process.

## Verify

Log in via SSH (the display will be running Cog). The Cog browser starts automatically on boot in fullscreen kiosk mode.

Check the browser service is running:

```bash
systemctl status cog
```

Test DRM/KMS display output:

```bash
modetest -M <drm-driver>    # list display modes
```

## Customize

### Change the Cog URL

The Cog browser loads a URL on startup. Point it at your own web application by configuring the Cog default URL. Add an overlay with your Cog configuration or pair this with another reference (e.g., `elixir`, `react-dashboard`) that serves a local web app.

### Add your web application

Combine this reference with a web-serving reference to display your own UI. For example, add a Phoenix or React app extension and point Cog at `http://127.0.0.1:4000`.

### Add or remove extensions

Edit `avocado.yaml` to customize the runtime:

```yaml
    extensions:
      - app
      - config-dev
      - avocado-ext-dev
      - avocado-ext-sshd-dev
      - avocado-ext-webkit         # the Cog browser
      - avocado-ext-docker         # add Docker support
      - avocado-bsp-{{ avocado.target }}
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev --profile sd
```
