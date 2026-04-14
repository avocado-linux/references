# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Rust System Vitals (Experimental)

This guide walks you through building and running the Rust system vitals reference on Avocado OS. The app cross-compiles a Rust binary that reads system stats from `/proc` and logs structured JSON to the journal.

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
avocado init --reference rust-vitals rust-app
cd rust-app
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference rust-vitals --target raspberrypi5 rust-app
cd rust-app
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs the Rust cross-compilation toolchain: `nativesdk-rust`, `nativesdk-cargo`, `packagegroup-rust-cross-canadian-avocado-<target>`, and target libraries `libstd-rs` and `libstd-rs-dev`.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `rust-compile.sh` inside the SDK container, which:

1. Discovers the Rust target triple from `RUST_TARGET_PATH` (e.g., `x86_64-avocado-linux-gnu`)
2. Clears SDK-injected `RUSTFLAGS` to avoid conflicts
3. Generates `.cargo/config.toml` with the correct `--sysroot` and linker flags
4. Runs `cargo build --release --target $RUST_TARGET`

Then `rust-install.sh` locates the cross-compiled binary and copies it to `/usr/bin/ref_rust` in the extension sysroot.

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

Log in as `root` with an empty password. The service starts automatically on boot.

Check the service is running:

```bash
systemctl status ref-rust
journalctl -u ref-rust -f
```

You should see output like:

```json
{"hostname":"avocado-qemux86-64","uptime":42,"mem_total_kb":977972,"mem_free_kb":821488,"load_1m":"0.12"}
```

## Customize

### Edit the Rust source

Modify `ref-rust/src/main.rs` to change the vitals collected or the output format.

### Add Cargo dependencies

Edit `ref-rust/Cargo.toml`:

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
