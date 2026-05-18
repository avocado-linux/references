---
language: Python
targets:
  - "*"
topics:
  - container
  - docker
  - python
  - air-gapped
---

# Docker Container — Local Tarball

A reference runtime that builds a Docker image **locally on the developer's machine**, saves it to a tarball with `docker save`, ships the tarball into the Avocado image at `avocado build` time, loads it into the engine on first boot, and runs it as a systemd-supervised service. The reference uses a small Python 3.10 + Flask app to serve a "Hello from Avocado" page on port 8080.

- No registry required &mdash; works for **air-gapped builds**, internal-only images, customer-private workloads
- The image is built once on the developer machine and shipped as a single artifact (`build/hello.tar`)
- Demonstrates **runtime version isolation** &mdash; the container ships Python 3.10, while Avocado's host userland uses Python 3.12; both can coexist on the same device
- Standard `docker run` semantics inside a systemd unit &mdash; no on-device agent or fleet daemon
