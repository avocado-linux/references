---
language: Python
targets:
  - "*"
topics:
  - container
  - docker
---

# Docker Container — Registry Pull

A reference runtime that pulls a public Docker image from a registry during `avocado build`, seeds it into the device's var partition, and runs it as a systemd-supervised service. The reference uses a small Python 3.11 + Flask container (`docker.io/peridionick/hello-flask:py311`) to serve a "Hello from Avocado" page on port 8080.

- Pulls the image **once at build time** — the device works offline at runtime, with no registry access required after deploy
- Multi-architecture: the same reference builds for any supported target; the registry pull is target-platform-aware
- Demonstrates **runtime version isolation** — the container ships Python 3.11, while Avocado's host userland uses Python 3.12; both can coexist on the same device
- Standard `docker run` semantics inside a systemd unit — no on-device agent or fleet daemon
