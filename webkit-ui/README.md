---
language: Shell
targets:
  - raspberrypi5
  - raspberrypi4
  - reterminal
  - reterminal-dm
  - icam-540
  - jetson-orin-nano-devkit
  - jetson-agx-orin-devkit
topics:
  - ui
  - web
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> WebKit UI

A development runtime for display-capable hardware with the Cog WebKit browser pre-installed. Boots into a fullscreen kiosk browser backed by DRM/KMS — use it as a starting point for building embedded web UIs or as a test environment for display bring-up.

- Cog WebKit browser in fullscreen kiosk mode via DRM/KMS
- Supports Raspberry Pi 4/5, Seeed reTerminal, Advantech ICAM-540, and NVIDIA Jetson
- Includes libdrm-tests for display and GPU diagnostics
- Ready-to-use base for embedding a web application UI on-device
