---
language: Python
targets:
  - qemux86-64
  - raspberrypi5
  - raspberrypi4
topics:
  - python
  - uv
  - multi-version
  - cross-compilation
  - nats
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python Multi-Version with UV

A reference runtime that runs three Python applications on one device, each pinned to a different CPython version (3.11, 3.12, and 3.14), built with [uv](https://docs.astral.sh/uv/). Each app installs its own interpreter and its own native dependencies at build time, so version-incompatible dependency sets coexist on a single image. The three apps discover each other over a local NATS broker.

- Pin each app to its own CPython via `uv python install`, shipped inside the app's extension
- Contrast that with an app that runs on the device's system Python (3.12, the Yocto build's own interpreter)
- Compile native wheels (`numpy`, `scipy`) against the correct interpreter and target architecture, no per-package Yocto recipe required
- Keep each app's packages isolated in its own directory, so divergent dependency locks never collide
- Coordinate the three interpreters over NATS to confirm the whole fleet is live
