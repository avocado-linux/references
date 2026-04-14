# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Python MQTT Telemetry

This guide walks you through building and running the Python MQTT telemetry reference on Avocado OS. The app collects system vitals and publishes them to a public MQTT broker where you can observe them in real time.

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
avocado init --reference python-mqtt python-mqtt
cd python-mqtt
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference python-mqtt --target raspberrypi5 python-mqtt
cd python-mqtt
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

The build step runs `app-compile.sh` inside the SDK container, which uses `uv pip install --target app/packages requests paho-mqtt` to download the MQTT client and HTTP libraries. Then `app-install.sh` copies the packages into the extension sysroot at `/usr/lib/app/packages/`.

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

Log in as `root` with an empty password. The app service starts automatically on boot.

Check the service is running:

```bash
systemctl status app
```

Watch telemetry logs:

```bash
journalctl -u app -f
```

You should see output like:

```
app starting
  mqtt: broker.emqx.io:1883, topic=avocado/a8f3e2b1c4d5e6f7a8b9c0d1e2f3a4b5/telemetry, interval=10s
  http: https://httpbin.org/get, interval=45s
Connected to broker.emqx.io:1883 (rc=Success)
[mqtt] published: {"device": "a8f3e2b1c4d5e6f7a8b9c0d1e2f3a4b5", "timestamp": 1711234567, "uptime_secs": 42, ...}
```

The device identifier is the systemd machine ID (`/etc/machine-id`) — a 32-character hex string generated once at first boot, unique per device, stable across reboots and OTA updates.

### View messages online

The app publishes to the free public EMQX broker. To observe your messages:

1. Go to [mqttx.app](https://mqttx.app/) and open the web client
2. Connect to `broker.emqx.io` on port `1883`
3. Subscribe to `avocado/+/telemetry` — the `+` wildcard matches any device's machine ID, so you'll see messages from all your devices without needing to know IDs upfront
4. You will see JSON telemetry messages arriving every 10 seconds

## Customize

### Change the broker or intervals

Edit `app/overlay/usr/local/bin/app.py`:

```python
BROKER = "broker.emqx.io"       # or your own broker
PORT = 1883
MQTT_INTERVAL = 10               # publish telemetry every N seconds
HTTP_INTERVAL = 45               # HTTP check every N seconds
HTTP_ENDPOINT = "https://httpbin.org/get"
```

### Add pip dependencies

Edit `app-compile.sh` to add packages:

```bash
uv pip install --target app/packages requests paho-mqtt psutil
```

### Change the telemetry payload

The telemetry collection logic is in `app/overlay/usr/local/bin/app.py`. Modify the `collect_telemetry()` function to add or remove fields.

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
