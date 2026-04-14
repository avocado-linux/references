# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with React Dashboard

This guide walks you through building and running the React dashboard reference on Avocado OS. The app compiles a React + Vite + Tailwind CSS frontend inside the SDK container and serves it alongside a system metrics API via Express.

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
avocado init --reference react-dashboard react-dashboard
cd react-dashboard
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference react-dashboard --target raspberrypi5 react-dashboard
cd react-dashboard
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-nodejs`, `nativesdk-nodejs-npm`, and `nativesdk-ca-certificates` for building the React app.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `reactjs-compile.sh` inside the SDK container, which:

1. Runs `npm install` to fetch React, Vite, Tailwind CSS, Express, and all dependencies
2. Runs `npm run build` to produce the optimized static frontend in `dist/`

Then `reactjs-install.sh` copies `dist/`, `node_modules/`, `package.json`, and `server.js` into the extension sysroot at `/usr/lib/ref-reactjs/`.

## Deploy

### QEMU

For QEMU targets, provision and boot the VM with port forwarding:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev --host-fwd "4000-:4000"
```

To also SSH in from another terminal:

```bash
avocado sdk run -iE vm dev --host-fwd "2222-:22" --host-fwd "4000-:4000"

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

Log in as `root` with an empty password. The dashboard service starts automatically on boot.

Open your browser to [http://localhost:4000](http://localhost:4000) (QEMU) or `http://<device-ip>:4000` (hardware).

Check the service is running:

```bash
systemctl status ref-reactjs
journalctl -u ref-reactjs -f
```

The dashboard shows:

- CPU usage with per-core breakdown and history chart
- Memory usage with cached/total breakdown
- Disk usage, load average, uptime
- Temperature (hardware only)
- Network interface RX/TX stats
- Top processes by memory usage

## Customize

### Edit the React frontend

Modify components in `ref-reactjs/src/`:

- `src/App.jsx` — main dashboard layout
- `src/components/` — StatCard, ProgressBar, MiniChart, NetworkCard, ProcessList, Tabs

### Edit the Express backend

Modify `ref-reactjs/server.js` to add API endpoints or change the stats collected from `/proc` and `/sys`.

### Add npm dependencies

Edit `ref-reactjs/package.json` to add packages — they'll be installed during `reactjs-compile.sh`.

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
