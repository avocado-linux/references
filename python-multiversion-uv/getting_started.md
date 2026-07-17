# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Python Multi-Version with UV

This guide builds and runs three Python apps on one Avocado OS device, each pinned to a different CPython version (3.11, 3.12, 3.14), all installed with [uv](https://docs.astral.sh/uv/) at build time. Two apps ship their own standalone interpreter inside their extension; one runs on the device's system Python. The three form a producer → processor → aggregator data pipeline over a local NATS broker.

The pattern mirrors a real fleet where independent apps pin different Python versions from their own dependency sets and collaborate over a message bus.

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
avocado init --reference python-multiversion-uv python-multiversion-uv
cd python-multiversion-uv
```

To target a Raspberry Pi 5 instead of the default QEMU target:

```bash
avocado init --reference python-multiversion-uv --target raspberrypi5 python-multiversion-uv
cd python-multiversion-uv
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-uv`, used by every app's compile step.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

Each app has its own compile step:

- **app311** and **app314** run `uv python install 3.11` / `uv python install 3.14` inside the SDK. uv detects the target architecture automatically (native x86_64 for QEMU, emulated aarch64 for the Pi), downloads the matching [python-build-standalone](https://github.com/astral-sh/python-build-standalone) interpreter, installs each app's dependencies against it, and ships the interpreter plus `app/packages` inside the extension.
- **app312** installs its dependencies against the SDK's own Python (3.12, the same interpreter the device ships as `/usr/bin/python3`), so no interpreter is bundled.

Because each app resolves independently, versions diverge on purpose. On a recent build numpy resolves to 2.4.6 on 3.11 but 2.5.1 on 3.12 and 3.14 — exactly the isolation the reference demonstrates.

## Deploy

### QEMU

Launch the VM (serial console attaches to your terminal):

```bash
avocado provision dev
avocado sdk run -iE vm dev
```

### SD card targets (Raspberry Pi, NXP, STMicroelectronics)

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device and apply power.

## Verify

Log in as `root` with an empty password. All three app services and the NATS broker start automatically on boot.

Each app logs a single `startup` line reporting the interpreter it runs on and the native dependencies it loaded:

```bash
journalctl -u app311 -o cat
```

```json
{"event": "startup", "app": "app311", "role": "producer", "python": "3.11.14", "executable": "/usr/lib/app311/python/bin/python3.11", "deps": {"numpy": "2.4.6", "nats-py": "2.15.0"}}
```

```bash
journalctl -u app312 -o cat
```

```json
{"event": "startup", "app": "app312", "role": "processor", "python": "3.12.13", "executable": "/usr/bin/python3", "deps": {"numpy": "2.5.1", "nats-py": "2.15.0", "mcap": "1.4.0"}}
```

```bash
journalctl -u app314 -o cat
```

```json
{"event": "startup", "app": "app314", "role": "aggregator", "python": "3.14.2", "executable": "/usr/lib/app314/python/bin/python3.14", "deps": {"numpy": "2.5.1", "scipy": "1.18.0", "nats-py": "2.15.0"}}
```

The `python` field of each app is a different version, and every native dependency loads. numpy diverges (2.4.6 on 3.11 vs 2.5.1 on 3.12 and 3.14) because each app resolved against its own interpreter.

### The pipeline

The three apps form a data pipeline over NATS, each stage on its own interpreter:

- **app311 (producer, 3.11)** generates a window of samples with numpy and publishes it on `fleet.pipeline.raw`.
- **app312 (processor, 3.12)** consumes each window, reduces it to numpy statistics (mean, std, RMS, and the FFT peak frequency), and republishes on `fleet.pipeline.processed`.
- **app314 (aggregator, 3.14)** consumes the statistics, fits a trend across a rolling window with scipy, and logs the result.

Watch the data flow through the first two stages:

```bash
journalctl -u app311 -o cat | grep produced    # {"event": "produced", "seq": 7, "n": 64}
journalctl -u app312 -o cat | grep processed   # {"event": "processed", "seq": 7, "peak_hz": 5.0}
```

Once the aggregator has seen a full window it logs `pipeline_complete`, whose `chain` names all three interpreters that touched the data:

```bash
journalctl -u app314 -o cat | grep pipeline_complete
```

```json
{"event": "pipeline_complete", "seq": 11, "chain": {"producer": {"app": "app311", "python": "3.11.14"}, "processor": {"app": "app312", "python": "3.12.13"}, "aggregator": {"app": "app314", "python": "3.14.2"}}, "result": {"window": 3, "rms_mean": 0.763675, "rms_trend_slope": -0.007031, "peak_hz": 5.0}}
```

That single `pipeline_complete` line is the whole-system success signal: three apps, three interpreters, one device, collaborating on one result over NATS. The `peak_hz: 5.0` is the tone app311 injected, recovered by app312's FFT — proof the data really flowed through every stage.

## Customize

### Change an app's dependencies

Edit the app's compile script (`app311-compile.sh`, `app312-compile.sh`, or `app314-compile.sh`) and add packages to the `uv pip install` line:

```bash
uv pip install --target "$APPDIR/packages" --python "$PYBIN" \
  numpy \
  nats-py \
  pandas
```

Then add the import name and distribution name to the `NATIVE` list at the top of the app so the startup log reports it (`app/overlay/usr/local/bin/app311.py`):

```python
NATIVE = [("numpy", "numpy"), ("nats", "nats-py"), ("pandas", "pandas")]
```

### Change a pinned Python version

Edit the `PYVER` line in the compile script and the interpreter path in the systemd unit. For example, to move app311 from 3.11 to 3.13, set `PYVER=3.13` in `app311-compile.sh` and update `ExecStart` in `app311/overlay/usr/lib/systemd/system/app311.service` to `/usr/lib/app311/python/bin/python3.13`.

### Add a fourth app

Copy an `app3NN` extension block in `avocado.yaml`, its `sdk.compile` entry, and its three build scripts, then add it to the `dev` runtime's `extensions` list.

### Rebuild after changes

```bash
avocado build
avocado provision dev
```
