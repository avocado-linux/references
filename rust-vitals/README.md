---
language: Rust
targets:
  - "*"
topics:
  - monitoring
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Rust System Vitals

A reference runtime that demonstrates how to cross-compile and deploy a Rust application on Avocado OS. The app is a system vitals reporter — a single static binary that reads from `/proc` and logs structured JSON to the journal. No runtime, no interpreter, no dependencies on the device.

- Cross-compile Rust with Cargo using automatic target triple discovery from the SDK environment
- Generate `.cargo/config.toml` with correct sysroot and linker flags for the target
- Deploy a single static binary with zero runtime dependencies
- Read system vitals from `/proc` and output structured JSON to the systemd journal
