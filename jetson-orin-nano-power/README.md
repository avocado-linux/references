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
- A way in on a fresh board: a serial console that logs in as root, then SSH with your key
- `verify-power.sh` reads the module's INA3221 power monitor and reports idle watts

Every extension comes from the package feed, so there is nothing to compile. See [getting_started.md](getting_started.md)
to build and provision it.
