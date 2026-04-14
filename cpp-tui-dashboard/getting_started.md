# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with C++ CMake Syslog Dashboard

This guide walks you through building and running the C++ CMake syslog dashboard reference on Avocado OS. The app reads the systemd journal and renders a live TUI with message rates, severity breakdowns, and top logging units.

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
avocado init --reference cpp-tui-dashboard cpp-tui-dashboard
cd cpp-tui-dashboard
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference cpp-tui-dashboard --target raspberrypi5 cpp-tui-dashboard
cd cpp-tui-dashboard
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs the cross-compilation toolchain along with `nativesdk-cmake`.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which generates a CMake toolchain file from the SDK environment, fetches FTXUI via `FetchContent`, and cross-compiles the dashboard binary. Then `app-install.sh` copies the binary into the extension sysroot at `/usr/bin/syslog-dashboard`.

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

Log in as `root` with an empty password. The app service starts automatically on boot. When running as a service (no TTY), it logs periodic summaries to the journal.

Check the service is running:

```bash
systemctl status app
```

Watch the headless output:

```bash
journalctl -u app -f
```

You should see output like:

```
syslog-dashboard: 142 total | 8 msg/s | ERR:2 WARN:15 INFO:125
```

### Interactive TUI

For the full terminal dashboard, SSH into the device and run it directly:

```bash
syslog-dashboard
```

You will see a live dashboard with:

- A message rate sparkline (60-second window)
- Severity counters (EMERG through DEBUG, color-coded)
- Top logging units ranked by message count
- A scrolling list of recent journal entries

Press `q` to quit.

## Customize

### Change the journal filter

Edit `app/src/main.cpp` and modify the `journalctl` command in the `journal_reader` function to filter by unit, priority, or time range:

```cpp
// Only show errors and above
FILE* pipe = popen("journalctl -f -o export --no-pager -p err 2>/dev/null", "r");

// Only show a specific unit
FILE* pipe = popen("journalctl -f -o export --no-pager -u myapp.service 2>/dev/null", "r");
```

### Adjust the UI refresh rate

The UI refreshes every 500ms by default. Change the interval in the `run_tui` function:

```cpp
std::this_thread::sleep_for(std::chrono::milliseconds(250));  // faster refresh
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
