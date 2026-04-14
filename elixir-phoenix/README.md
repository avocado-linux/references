---
language: Elixir
targets:
  - "*"
topics:
  - web
  - ui
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Elixir Phoenix

A reference runtime that demonstrates how to build and deploy an Elixir Phoenix LiveView application as an Avocado OS extension. The app is compiled as an OTP release inside the SDK container and displayed on-device via the Cog WebKit browser.

- Compile an Elixir Phoenix app with Mix and deploy as an OTP release
- Install Elixir, Erlang/OTP, and Node.js toolchains via native SDK packages
- Serve a Phoenix LiveView UI locally and display it in the Cog embedded browser
- Run as a systemd-managed service that starts on boot
