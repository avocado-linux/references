# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with C GPIO Toggle

This guide walks you through building and running the C GPIO toggle reference on Avocado OS. The app uses libgpiod v2 to toggle a GPIO line every second on a Raspberry Pi 5.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- Raspberry Pi 5
- SD card

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference c-gpio c-gpio
cd c-gpio
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image with the Meson build system, cross-compilation toolchain, and `libgpiod-dev` headers.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which generates Meson cross-compilation files from the SDK environment and runs `meson setup` + `ninja` to cross-compile `gpio-toggle` for aarch64. Then `app-install.sh` runs `ninja install` to copy the binary into the extension sysroot at `/usr/bin/gpio-toggle`.

## Deploy

### SD card

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the Raspberry Pi 5 and apply power.

## Verify

SSH into the Pi or connect via serial console. Log in as `root` with an empty password. The app service starts automatically on boot.

Check the service is running:

```bash
systemctl status app
```

Watch GPIO toggle logs:

```bash
journalctl -u app -f
```

You should see output like:

```
gpio-toggle starting
GPIO chips:
  gpiochip0 [pinctrl-bcm2712] (54 lines)
  gpiochip4 [pinctrl-rp1] (54 lines)
Opening /dev/gpiochip0, line 17
Toggling line 17 every 1s
[1711234567] line 17 = HIGH
[1711234568] line 17 = LOW
```

To verify the GPIO is toggling, attach an LED (with a resistor) or a multimeter to GPIO 17.

## Customize

### Change the GPIO chip or line

Edit `app/src/main.c`:

```c
#define DEFAULT_CHIP "/dev/gpiochip0"
#define DEFAULT_LINE 17
#define TOGGLE_INTERVAL_S 1
```

Or pass them as command-line arguments by editing `app/overlay/usr/lib/systemd/system/app.service`:

```ini
ExecStart=/usr/bin/gpio-toggle /dev/gpiochip4 22
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev --profile sd
```
