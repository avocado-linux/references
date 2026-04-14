---
language: Python
targets:
  - "*"
topics:
  - mqtt
  - telemetry
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python MQTT Telemetry

A reference runtime that demonstrates how to build a Python application with pip dependencies as an Avocado OS extension. The app collects device telemetry (uptime, memory, CPU load, temperature) and publishes it over MQTT to a public broker, using the device's systemd machine ID as a stable, unique identifier.

- Bundle pip packages into a system extension when they are not available as RPMs
- Run a systemd-managed Python service that starts on boot
- Identify each device by `/etc/machine-id` — unique, stable across reboots and OTA updates
- Publish structured JSON telemetry over MQTT to `avocado/<machine-id>/telemetry`
- Make HTTP health check requests on a schedule
