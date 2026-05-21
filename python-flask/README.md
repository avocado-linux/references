---
language: Python
targets:
  - "*"
topics:
  - monitoring
  - web
  - ui
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python Flask Dashboard

A reference runtime that demonstrates how to build a Python Flask web application as an Avocado OS extension. The app serves a real-time device dashboard that displays CPU, memory, disk, network, and temperature metrics, along with a JSON API for programmatic access.

- Bundle pip packages (`flask`) into a system extension when they are not available as RPMs
- Serve a live single-page dashboard with sortable process table and history charts
- Expose JSON API endpoints at `/api/stats` and `/api/processes`
- Run a systemd-managed Python service that starts on boot
