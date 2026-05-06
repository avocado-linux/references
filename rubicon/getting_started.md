# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Rubicon

This guide walks you through building and running the Rubicon development runtime on a Raspberry Pi 4 or 5. Rubicon gives you a batteries-included dev environment with USB gadget networking, WiFi, Docker, and Cockpit — connect your Pi over USB-C and start building.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- Raspberry Pi 5 (or Raspberry Pi 4)
- USB-C cable (for USB gadget networking) or WiFi network
- SD card

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference rubicon rubicon
cd rubicon
```

To use a Raspberry Pi 4 instead of the default Pi 5:

```bash
avocado init --reference rubicon --target raspberrypi4 rubicon
cd rubicon
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

There are no compile steps — Rubicon is built entirely from overlay files and pre-built packages.

## Deploy

### SD card

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the Raspberry Pi and apply power.

## Verify

### USB gadget networking

Connect the Pi to your computer via USB-C. After boot, a virtual Ethernet interface appears on your host. The Pi runs dnsmasq on this interface and advertises itself via Avahi/mDNS.

SSH in:

```bash
ssh root@rubicon.local
```

The default password is empty.

### WiFi

WiFi connects automatically if configured. Edit `overlay/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` before building to add your network:

```
network={
    ssid="YourSSID"
    psk="YourPassword"
}
```

### Serial console

Connect to the USB serial console:

```bash
screen /dev/tty.usbmodemXXXX 115200
```

### Cockpit

Open `http://rubicon.local:9090` in your browser for the Cockpit web management UI.

### Docker

Docker is pre-installed and running:

```bash
docker run --rm hello-world
```

Multi-arch containers work via QEMU user-static binfmt:

```bash
docker run --rm --platform linux/arm64 alpine uname -m
```

## Customize

### Configure WiFi

Edit `overlay/etc/wpa_supplicant/wpa_supplicant-wlan0.conf`:

```
ctrl_interface=/run/wpa_supplicant
ctrl_interface_group=wheel
update_config=1

network={
    ssid="MyNetwork"
    psk="MyPassword"
}
```

### Modify boot config

Target-specific Raspberry Pi boot configuration is in `stone/<target>/bootfiles/config.txt`.

### Add or remove extensions

Edit `avocado.yaml` to add or remove extensions:

```yaml
    extensions:
      - rubicon
      - config-dev
      - avocado-ext-cockpit       # remove to save space
      - avocado-ext-docker        # remove if Docker not needed
      - avocado-ext-dev
      - avocado-ext-sshd-dev
      - avocado-ext-cli
      - avocado-bsp-{{ avocado.target.board }}
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev --profile sd
```
