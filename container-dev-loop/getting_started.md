# Getting Started with Container Dev Loop

This guide walks you through the container dev loop on an Avocado OS device. You build a container image on your host with `docker build`, and `avocado container dev` ships only the changed layers to the running device and restarts the service there. There is no reflash and no OS rebuild between iterations.

The reference ships a `dev` runtime with a `container-hello` systemd service that runs `docker.io/peridionick/hello-flask:py311` on port 8080. The `container_dev` block in `avocado.yaml` maps the host-side image `peridionick/hello-flask:py311` to that service.

Nothing in this guide records a run: the Deploy and Verify sections describe the steps you perform and what the container dev mode guide says you should see. Hot reload through this reference has not been verified on any target yet.

## Prerequisites

- Linux or macOS host with Docker (or Podman) running. The watcher reads tag events from the engine CLI, and the SDK needs Docker.
- The latest [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview). This reference requires `>=0.41.0`.
- A target from the reference's `supported_targets`: `qemux86-64` (default) or `imx93-frdm`.
- A device running the provisioned `dev` runtime that your host can reach over SSH as `root@<device>`.
- `avocado-ext-sshd-dev` on the device. Container dev mode bootstraps the device over SSH, so a target without an SSH server cannot be bootstrapped. The reference's `hello` overlay adds an sshd drop-in for the key path, so the 0.1.0 package in the feed is enough.
- Control (5600) and bulk read (5599) ports on your host reachable from the device. Opening only the control port is the usual reason a sync appears to stall.

## Initialize

```bash
avocado init --reference container-dev-loop container-dev-loop
cd container-dev-loop
```

All remaining commands run from this directory on your host.

## Install

```bash
avocado install -f
```

This syncs the SDK toolchain and the runtime extensions. The `sdk.packages` block in `avocado.yaml` declares the cross toolchain because `avocado-ext-container-agent-dev` is compiled for the target at build time. Without it the build fails inside a dependency's build script.

## Build

```bash
avocado build
```

The build produces the `dev` runtime. It includes the project-local `hello` extension (the `container-hello.service` unit, enabled in both its sysext and confext), Docker, the container dev agent, the SSH server and the board support package. The `hello` extension declares `docker.io/peridionick/hello-flask:py311` to be primed into `/var` at runtime build, with the intent that the device does not need a registry at first boot. Priming is not verified: the build log does not show the step. Until you have confirmed it on your build, give the device registry access at first boot so it can pull the image.

## Deploy

Provision the device once. This erases the target media, so confirm the device first. List the profiles available for your target:

```bash
avocado provision --list
```

Then provision the `dev` runtime with a profile from that list:

```bash
avocado provision dev --profile <profile>
```

The `dev` permissions profile sets an empty root password and is not for production.

Boot the device and find its IP address from the console (`ip addr`). Substitute it for `<device-ip>` below.

### Give the host SSH access

Container dev mode needs `root@<device-ip>` reachable over SSH with your key accepted. `avocado-ext-sshd-dev` 0.1.0 reads `.ssh/authorized_keys`, so the `hello` overlay installs `/etc/ssh/sshd_config.d/10-authorized-keys.conf`, which sets `AuthorizedKeysFile /var/lib/ssh/authorized_keys.d/root`. That file does not exist on a freshly provisioned device, so create it from the console as root and paste your public key:

```bash
mkdir -p /var/lib/ssh/authorized_keys.d
echo "<your public key>" > /var/lib/ssh/authorized_keys.d/root
chmod 600 /var/lib/ssh/authorized_keys.d/root
```

Check from your host:

```bash
ssh root@<device-ip> true
```

Then point the CLI at the device. The `avocado container dev` subcommands take no positional arguments:

```bash
export AVOCADO_CONTAINER_DEV_DEVICE=root@<device-ip>
```

### Start the loop

```bash
avocado container dev up
```

`up` mints a per-project CA and tokens, starts the embedded registry, the watcher and the control WebSocket on your host, and writes the bootstrap to the device once over SSH. It then leaves the loop running. Run the remaining commands in a second terminal.

## Verify

Check the service on the device:

```bash
ssh root@<device-ip> systemctl status container-hello.service
ssh root@<device-ip> docker ps
```

The container dev mode guide describes the unit as running and the container `container-hello` as listed by `docker ps`. Then request the page from your host:

```bash
curl http://<device-ip>:8080
```

The page is served by the `hello-flask:py311` container and reports a container Python of 3.11.

Check the host side of the loop:

```bash
avocado container dev status
```

`status` reports registry, watcher and last-sync state.

To confirm a hot reload, rebuild the watched tag on your host:

```bash
docker build -t peridionick/hello-flask:py311 app
```

Per the container dev mode guide, the watcher sees the tag event, pushes only the changed layers, and the agent on the device pulls them and restarts `container-hello`. Watch it from the device:

```bash
ssh root@<device-ip> journalctl -u container-agent-dev -f
```

Docker builds on older daemons (before Docker 23) emit no tag event for BuildKit builds, and a `--platform` cross-build never does. In those cases trigger the sync yourself:

```bash
avocado container dev sync
```

The `app/` directory holds a minimal Dockerfile that layers one file on the published image, so the rebuild has a changed layer to ship. Replace it with your own application when you have one.

Reading logs: the container runs on the device, not on your host, so `docker logs` on your host reports no such container. Use `ssh root@<device-ip> docker logs -f container-hello`.

## Customize

- Your own image: set `container_dev.images[].ref` in `avocado.yaml` to the tag you build, byte for byte, and `service` to the unit that runs it. Update the image in `docker_images` of the `hello` extension and in `overlay/usr/lib/systemd/system/container-hello.service` to match.
- The service must recreate the container from the image tag on every start. The shipped unit does so with `docker rm -f` followed by `docker run`. A unit that restarts an existing container keeps running the old code.
- Ports: change `-p 8080:8080` in the unit. Override the dev loop ports with `AVOCADO_CONTAINER_DEV_PORT` (bulk read, default 5599) and `AVOCADO_CONTAINER_DEV_WS_PORT` (control, default 5600).
- Architecture: when your host differs from the target, build with `docker build --platform <platform> -t <ref> app`, using `linux/amd64` for `qemux86-64` and `linux/arm64` for `imx93-frdm`, and then run `avocado container dev sync`.
- Disk: `avocado container dev prune` garbage-collects the host registry store.
- Stop the loop with `avocado container dev down`. The device keeps running the last image it was given.
- Only one runtime per config may carry a `container_dev` block, and `avocado-ext-container-agent-dev` must not be part of a production runtime.
