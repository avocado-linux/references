---
language: React
targets:
  - "*"
topics:
  - monitoring
  - web
  - ui
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> React Dashboard

A reference runtime that demonstrates how to build and deploy a React.js system monitoring dashboard on Avocado OS. The app is a full-stack web application — a Vite-built React frontend with Tailwind CSS served by an Express.js backend that reads system metrics from `/proc` and `/sys`.

- Build a React + Vite + Tailwind CSS frontend inside the SDK container using npm
- Serve a live dashboard with CPU, memory, disk, network, temperature, and process stats via Express
- Expose JSON API endpoints at `/api/stats` and `/api/processes`
- Run as a systemd-managed Node.js service that starts on boot
