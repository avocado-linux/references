---
language: C
targets:
  - raspberrypi5
topics:
  - gpio
  - cross-compilation
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> C GPIO Toggle

A reference runtime that demonstrates how to cross-compile a C application using the Meson build system in the Avocado SDK. The app uses libgpiod v2 to enumerate GPIO chips, request a line for output, and toggle it every second.

- Cross-compile C11 with Meson using the Avocado SDK's meson-wrapper
- Link against system libraries (`libgpiod`) from the Avocado package feed
- Install a compiled binary as a systemd service
- Use the libgpiod v2 API for GPIO chip enumeration and line control
