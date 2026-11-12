---
language: Shell
targets:
  - jetson-orin-nano
topics:
  - power
  - jetson
  - nvpmodel
---

# Jetson Orin Nano Power Management

A reference runtime for a battery-powered Jetson Orin Nano 8GB. It applies the 25 W power mode at boot and scales the CPU
and GPU frequency with load, so the module idles where JetPack idles instead of holding the GPU at its maximum clock.

- Power mode set at boot: `nvpower.service` and `nvpmodel.service` run from the board support extension
- CPU on `schedutil` and GPU on `simple_ondemand`, set by a confext unit that runs after `nvpmodel`
- `/var` grows to fill the storage on first boot with `avocado-ext-dev`
- A way in on a fresh board: the `dev` permissions profile gives root an empty password, on the serial console and over SSH
- `verify-power.sh` reads the module's INA3221 power monitor and reports idle watts
- A second runtime, `trt`, adds `trtexec` and the TensorRT, cuDNN and cuBLAS libraries from the feed, so the board runs a
  model without the `apt-get install nvidia-jetpack` step of a stock Ubuntu install

The extensions come from the package feed, and `avocado-ext-trt` only lists feed packages, so there is nothing to compile. See [getting_started.md](getting_started.md) to build and provision it.

## Depends on unpublished changes

The power mode and the governors come from `avocado-bsp-jetson-orin-nano`, which is not published with them yet. The BSP on the feed today (0.2.1) has no governors unit and leaves
`nvpmodel.service` and `nvpower.service` disabled, so a board flashed from the feed keeps the `performance` governors and
prints `power mode is not set!`. This reference works as described once the BSP change (bsp-jetson-orin-nano, in review) is
published.

To try the governors before then, clone the branch of that change next to the project and point the extension at it in
`avocado.yaml`:

```yaml
extensions:
  avocado-bsp-jetson-orin-nano:
    source:
      type: path
      path: ../bsp
```

Build with `avocado install -f` and `avocado build -r power`. That is how the figures in the JetPack comparison field note were
measured.
