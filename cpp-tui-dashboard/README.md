---
language: C++
targets:
  - "*"
topics:
  - monitoring
  - tui
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> C++ CMake Syslog Dashboard

A reference runtime that demonstrates how to build a C++ application with CMake and third-party libraries fetched at build time as an Avocado OS extension. The app renders a live terminal dashboard of the system journal using FTXUI.

- Cross-compile C++17 with CMake using the Avocado SDK toolchain
- Pull third-party libraries (FTXUI) via CMake FetchContent with no target-side dependencies
- Read the systemd journal in real time and display message rates, severity counts, and top logging units
- Automatically switch between interactive TUI mode and headless logging based on terminal detection
