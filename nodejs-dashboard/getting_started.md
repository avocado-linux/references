# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Node.js Dashboard

This guide walks you through building and running the Node.js dashboard reference on Avocado OS. The app serves a real-time device metrics dashboard and JSON API using Express, and renders it on-device through the Cog WebKit browser on display-capable hardware.

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
avocado init --reference nodejs-dashboard nodejs-dashboard
cd nodejs-dashboard
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference nodejs-dashboard --target raspberrypi5 nodejs-dashboard
cd nodejs-dashboard
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-nodejs` and `nativesdk-nodejs-npm` for building npm packages.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which runs `npm install --omit=dev` to install Express. Then `app-install.sh` copies `server.js`, `package.json`, and `node_modules/` into the extension sysroot at `/usr/lib/app/`.

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

Log in as `root` with an empty password. The app service starts automatically on boot, and on display-capable hardware the Cog browser opens to `http://127.0.0.1:5000` in fullscreen kiosk mode.

Open your browser to [http://localhost:5000](http://localhost:5000) (QEMU) or `http://<device-ip>:5000` (hardware) to view the dashboard from another machine.

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

Check the on-device browser service:

```bash
systemctl status cog
```

The dashboard polls the device every 2 seconds showing CPU usage, memory, disk, load average, uptime, temperature, network, and processes.

## Customize

### Change the port or add endpoints

Edit `app/overlay/usr/lib/app/server.js`:

```javascript
const PORT = 8080;  // change port
```

If you change the port, also update the Cog URL in `app/overlay/etc/default/cog-avocado` so the on-device browser points at the new port:

```
COG_URL=http://127.0.0.1:8080
```

### Change the Cog browser URL

Edit `app/overlay/etc/default/cog-avocado` to point Cog at a different page on the dashboard:

```
COG_URL=http://127.0.0.1:5000/
```

### Add npm dependencies

Edit `app/package.json`:

```json
{
  "dependencies": {
    "express": "^4.21.0",
    "ws": "^8.16.0"
  }
}
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
