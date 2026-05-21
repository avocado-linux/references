# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Heartbeat

This guide walks you through building and running the heartbeat reference on Avocado OS. The heartbeat extension is a shell-based systemd service that logs system vitals as JSON — the "hello world" for Avocado OS extension development.

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
avocado init --reference shell-heartbeat shell-heartbeat
cd shell-heartbeat
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference shell-heartbeat --target raspberrypi5 shell-heartbeat
cd shell-heartbeat
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

There is no compile step — the heartbeat extension is built entirely from overlay files (a shell script, systemd service, and config file).

## Deploy

### QEMU

For QEMU targets, provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

To SSH in from another terminal (linux):

```bash
avocado sdk run -iE vm dev --host-fwd "2222-:22"

# From another terminal:
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost
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

Log in as `root` with an empty password. The heartbeat service starts automatically on boot.

Check the service is running:

```bash
systemctl status heartbeat
```

Watch JSON vitals streaming in real time:

```bash
journalctl -u heartbeat -f
```

You should see output like:

```json
{"uptime":142,"mem_free_kb":412356,"mem_total_kb":524288,"load_1m":"0.03","ts":1740700000}
```

## Customize

### Change the sample interval

Edit `heartbeat/overlay/etc/heartbeat.conf`:

```sh
INTERVAL=10  # Sample every 10 seconds instead of 30
```

### Extend the vitals collected

Edit `heartbeat/overlay/usr/local/bin/heartbeat.sh` to add fields to the JSON output — disk usage, network traffic, temperature, etc.

### Rebuild after changes

After any change to overlay files, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
