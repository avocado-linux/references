---
language: Rust
targets:
  - raspberrypi0-2w
  - raspberrypi4
  - raspberrypi5
topics:
  - monitoring
  - metrics
  - prometheus
---

# Pi Metrics Exporter

A reference runtime that cross-compiles and deploys a small Rust HTTP service on Avocado OS. The service is a Prometheus metrics exporter: a single binary built with `tiny_http` that reads device health from `/proc` and `/sys` and serves it on port 9100. It has no runtime, no interpreter, and no dependencies on the device beyond the standard library and the HTTP server.

- Cross-compile Rust with Cargo using automatic target triple discovery from the SDK environment
- Generate `.cargo/config.toml` with the correct sysroot and linker flags for the target
- Serve the Prometheus text exposition format over HTTP using pure-Rust dependencies only
- Read CPU temperature, memory, uptime, and load average from `/proc` and `/sys`
- Run as a systemd service that starts on boot and listens on `0.0.0.0:9100`

## Endpoints

- `GET /metrics`: Prometheus text exposition format
- `GET /healthz`: returns `ok`
- `GET /status`: the same metrics as JSON
