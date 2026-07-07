# Getting Started with Pi Metrics Exporter

This guide walks you through building and running the Pi Metrics Exporter reference on Avocado OS. The app cross-compiles a Rust HTTP service that reads device health from `/proc` and `/sys` and serves it as Prometheus metrics on port 9100.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

For hardware targets, you will also need:

- Your target device and any required accessories (SD card, USB cable, serial console adapter)
- See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements

## Initialize

Initialize a new project from the reference:

```bash
avocado init --reference pi-metrics-exporter pi-metrics-exporter
cd pi-metrics-exporter
```

The reference defaults to the `raspberrypi4` target. To target another Raspberry Pi, pass `--target`:

```bash
avocado init --reference pi-metrics-exporter --target raspberrypi5 pi-metrics-exporter
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs the Rust cross-compilation toolchain: `nativesdk-rust`, `nativesdk-cargo`, `packagegroup-rust-cross-canadian-avocado-<target>`, and the target libraries `libstd-rs` and `libstd-rs-dev`.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `rust-compile.sh` inside the SDK container, which:

1. Discovers the Rust target triple from `RUST_TARGET_PATH` (e.g., `aarch64-avocado-linux-gnu`)
2. Clears SDK-injected `RUSTFLAGS` to avoid conflicts
3. Generates `.cargo/config.toml` with the correct `--sysroot` and linker flags
4. Runs `cargo build --release --target $RUST_TARGET`

Then `rust-install.sh` copies the cross-compiled binary to `/usr/bin/pi_metrics` in the extension sysroot.

## Deploy

Insert an SD card and provision it:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the Raspberry Pi and apply power. On first boot the extension's service starts automatically.

## Verify

Log in as `root` with an empty password. The service starts automatically on boot.

Check the service is running:

```bash
systemctl status pi-metrics
```

Then query the exporter from any host on the same network, using the device's IP:

```bash
curl http://<device-ip>:9100/healthz
curl http://<device-ip>:9100/metrics
```

You should see output like:

```text
# HELP pi_cpu_temperature_celsius CPU temperature in degrees Celsius
# TYPE pi_cpu_temperature_celsius gauge
pi_cpu_temperature_celsius 38.9
# HELP pi_memory_total_bytes Total memory in bytes
# TYPE pi_memory_total_bytes gauge
pi_memory_total_bytes 8185634816
# HELP pi_uptime_seconds System uptime in seconds
# TYPE pi_uptime_seconds gauge
pi_uptime_seconds 106.0
# HELP pi_load_average Load average
# TYPE pi_load_average gauge
pi_load_average{interval="1m"} 0.05
```

## Point Prometheus at it

Add the device as a scrape target in your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: avocado-device
    static_configs:
      - targets: ["<device-ip>:9100"]
```

## Customize

### Edit the Rust source

Modify `pi-metrics/src/main.rs` to change the metrics collected or add new ones.

### Add Cargo dependencies

Edit `pi-metrics/Cargo.toml`. Keep dependencies pure-Rust so they cross-compile without a C toolchain or OpenSSL:

```toml
[dependencies]
tiny_http = "0.12"
```

### Rebuild after changes

```bash
avocado build
avocado provision -r dev
```
