---
language: Python
targets:
  - qemux86-64
  - imx93-frdm
topics:
  - container
  - docker
  - container-dev
---

# Container Dev Loop

A reference runtime for container dev mode: a Python 3.11 + Flask container (`docker.io/peridionick/hello-flask:py311`) that starts at boot under a systemd unit, comes back after a reboot, and is designed to pick up a new image pushed from the host without a reflash. It is development only, a payload and not a platform component. For the plain pull-and-run pattern without the dev loop, see the `docker-registry` reference.

## Runtime wiring

The `dev` runtime in `avocado.yaml` combines these pieces:

- Extensions `avocado-ext-docker` (provides dockerd), `avocado-ext-container-agent-dev` (the on-device agent that receives pushed images), `avocado-ext-sshd-dev`, `avocado-ext-dev` and the board BSP extension, plus the project-local `hello` extension.
- `hello` is both a `sysext` and a `confext`. The sysext carries the `container-hello.service` unit under `usr/lib/systemd/system`, and the confext carries the `.wants` symlink that `enable_services` writes. Dropping either leaves the unit present but disabled.
- `hello` declares `docker_images` for `docker.io/peridionick/hello-flask:py311`, so the image is designed to be primed into the `/var` partition when the runtime is built, with the intent that first boot needs no registry contact. Priming is unverified, so give the device registry access at first boot until you have confirmed it. A local build of this project did not log the priming step, so confirm it on your own build.
- The `container_dev` block on the runtime enables container dev mode. Its `images` entry pairs `ref: peridionick/hello-flask:py311` with `service: container-hello`.

The container serves its page on port 8080. The `dev` permissions profile sets an empty root password, because container dev mode bootstraps the target over SSH as `root@<device>`.

## The `service` field is not optional

It names the systemd unit that owns the container. Without it, a sync pulls the new image while the old container keeps running.

With `service` set, the agent restarts `container-hello.service`, so `ExecStart` runs `docker run` again and resolves the tag to the newly pulled image. Without it, the agent falls back to restarting the existing container object, which stays bound to the image ID it was created with and never re-resolves the tag. The pull, the tag and the restart all report success, and the device goes on running the old image.

## Two sharp edges

**Image priming happens only on a runtime build.** `docker_images` is honored when the runtime is built. A standalone `avocado ext build` of the extension parses the key, ignores it and succeeds, producing an extension with no image in it.

**Units must live under `usr/lib/systemd/system`.** `enable_services` looks for the unit at exactly that path in the overlay and creates the `.wants` symlink only if it finds one. A unit placed under `etc/systemd/system` produces an extension that merges cleanly and leaves the unit disabled. The build prints a warning but still succeeds, so it is easy to miss.

## Not a production pattern

This runs a container from a hand-written unit shipped inside an extension. Nothing above that unit knows what it runs, so the fleet cannot ask which container a device should be running, verify that one is, or notice divergence. A container updated through the dev loop also persists across reboots, because the pulled image stays in `/var/lib/docker` under its tag. A device can therefore end up durably running an image that exists in no build and no fleet record, and a reprovision reverts it silently. Use the `docker-registry` reference for the plain pull-and-run pattern.

This README describes what the project is designed to show. It does not record a hot-reload or boot run on a board.
