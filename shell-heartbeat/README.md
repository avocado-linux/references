---
language: Shell
targets:
  - "*"
topics:
  - monitoring
  - telemetry
  - extensions
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Heartbeat (Experimental)

A tutorial runtime that demonstrates how to build a custom Avocado OS extension. The running example is a device heartbeat service — a shell script that collects system vitals (uptime, memory, load) and logs them as structured JSON to the journal. No compile step required.

- Build a custom extension using only overlay files and a systemd service
- Collect system vitals from `/proc` and output structured JSON to the journal
- Configure the heartbeat interval via a config file in the overlay
- Includes Avocado Connect and Tunnels extensions for remote device access
