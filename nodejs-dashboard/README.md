---
language: JavaScript
targets:
  - "*"
topics:
  - monitoring
  - web
  - ui
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Node.js Dashboard

A reference runtime that demonstrates how to build a Node.js web application as an Avocado OS extension and display it on-device via the Cog WebKit browser. The app serves a real-time device dashboard and JSON API using Express, with all metrics read directly from `/proc` and `/sys`.

- Bundle npm packages (`express`) into a system extension using the SDK container's Node.js toolchain
- Serve a live single-page dashboard with CPU, memory, disk, network, and temperature metrics
- Expose JSON API endpoints at `/api/stats` and `/api/processes`
- Render the dashboard on-device via the Cog embedded browser on display-capable targets
- Run as a systemd-managed service that starts on boot
