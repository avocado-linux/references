# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Python Flask Dashboard

This guide walks you through building and running the Python Flask dashboard reference on Avocado OS. The app serves a real-time device metrics dashboard and JSON API using Flask.

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
avocado init --reference python-flask python-flask
cd python-flask
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference python-flask --target raspberrypi5 python-flask
cd python-flask
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-uv` for pip package compilation.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which uses `uv pip install --target app/packages flask` to download Flask and its dependencies. Then `app-install.sh` copies the packages into the extension sysroot at `/usr/lib/app/packages/`.

## Deploy

### QEMU

For QEMU targets, provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev --host-fwd "5000-:5000"
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

Log in as `root` with an empty password. The app service starts automatically on boot.

Open your browser to [http://localhost:5000](http://localhost:5000) (QEMU) or `http://<device-ip>:5000` (hardware) to view the dashboard.

```bash
systemctl status app
journalctl -u app -f
```

You should see output like:

```
app starting
  device: avocado-qemuarm64
  dashboard: http://0.0.0.0:5000
```

The dashboard polls the device every 2 seconds showing CPU usage, memory, disk, load average, uptime, temperature, network, and a sortable process table.

## Customize

### Change the port

Edit `app/overlay/usr/local/bin/app.py`:

```python
app.run(host="0.0.0.0", port=8080)  # change port
```

### Add pip dependencies

Edit `app-compile.sh`:

```bash
uv pip install --target app/packages flask gunicorn
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
