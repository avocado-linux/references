# Getting Started with Docker Container — Registry Pull

This guide walks you through deploying Docker containers on an Avocado OS device end-to-end. It demonstrates two complementary delivery modes:

1. **Build-time bake-in** A public Docker image is pulled from Docker Hub during `avocado build` and seeded onto the device's var partition. The device boots with the image already cached locally and serves HTTP **without needing registry access at runtime** — the device works fully offline. The reference uses `docker.io/peridionick/hello-flask:py311` (Python 3.11 + Flask 3.0.3) for this path.

2. **Runtime swap.** Once the device is up, an included `container-swap` helper script pulls a *different* image and restarts the service in place — **no rebuild, no reflash**. The reference demonstrates this with `docker.io/peridionick/hello-flask-new:py314` (Python 3.14 + Flask 3.1.3) and includes a rollback to the originally-baked image that works **fully offline** because that image stays cached locally throughout.

By default Avocado OS ships with Python 3.12 (if on release 2024). This reference helps show the flexiblity of Avocado working with Docker containers as well as showing if you need to run other versions of Python.  

Following the guide end-to-end, you will:

- Build the runtime image and provision the device with the baked-in `hello-flask:py311` container.
- Verify the container is running Python 3.11 + Flask 3.0.3 (with the host's userland Python being 3.12 — the runtime version isolation is the load-bearing demo).
- Swap to `hello-flask-new:py314` at runtime and confirm the new container is now running Python 3.14 + Flask 3.1.3.
- Confirm the swap persists across a reboot.
- Roll back to the originally-baked image with no network access required.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or a working local Docker daemon) — required by the Avocado SDK to perform the registry pull during build
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A supported Avocado target — any from the [Support Matrix](https://docs.peridio.com/hardware/support-matrix). The reference is verified on `raspberrypi4`; see **Customize** for adding others.
- Internet access on the build machine and a network-reachable path to the device for the verify step

---

## Phase 1 — Build, deploy, and run the baked-in container

In Phase 1, you'll build the runtime image with `hello-flask:py311` (Python 3.11 + Flask 3.0.3) baked into the var partition, provision the device, and verify the container is up and serving HTTP. The device works fully offline at runtime — no registry access required after deploy.

### Initialize

```bash
avocado init --reference docker-registry docker-registry
cd docker-registry
```

### Install

```bash
avocado install -f
```

Downloads the SDK toolchain and runtime extensions. First-time install fetches several hundred megabytes; subsequent installs are cached.

### Build

```bash
avocado build
```

`avocado build` starts an ephemeral Docker daemon inside the SDK container, pulls `docker.io/peridionick/hello-flask:py311` for the target architecture, and seeds the image cache into the var partition. The pull happens at build time only — the device requires no registry access on first boot.

The reference ships a customized stone manifest at `stone/<target>/stone-<target>.json` that bumps the var partition to 2048 MB so the seeded image fits.

> **Multi-target note.** Only `raspberrypi4` ships with a pre-customized stone manifest. Building for a different target requires adding `stone/<target>/stone-<target>.json` — see **Customize → Adjust the var partition size**.

### Deploy

```bash
# Raspberry Pi 4 / 5 (SD card)
avocado provision -r dev --profile sd

```

For SD-card targets, follow the prompts. For Jetson, follow the USB recovery-mode prompts. After boot, `on_merge` hooks start `docker.service` and `container-app.service`.

#### Find the device IP

- **Serial console**: `ip addr` after login.

Substitute `<device-ip>` in the commands below.

### Verify

SSH into the device. The default `config` extension sets an empty root password for development:

```bash
ssh root@<device-ip>
```

#### Services are healthy

```bash
systemctl status docker.service container-app.service
```

Both should report `Active: active (running)`.

#### Image is local (no on-device pull)

```bash
docker images
```

Expected:

```
REPOSITORY                          TAG     IMAGE ID       CREATED        SIZE
peridionick/hello-flask   py311   abc123def456   X weeks ago    ~75MB
```

#### Hit the HTTP endpoint

From any machine on the same network as the device:

```bash
curl http://<device-ip>:8080
```

Expect HTML containing the line:

```
Container Python: 3.11.X (...)
```

#### Confirm Python 3.11 inside the container

For direct verification that the container is actually running Python 3.11 (not just claiming it in a response body):

```bash
docker exec container-app python --version
# → Python 3.11.X
```

Side-by-side proof of runtime isolation — same kernel, different Python:

```bash
echo "=== HOST ===" && python3 --version && uname -r
echo "=== CONTAINER ===" && docker exec container-app sh -c 'python --version && uname -r'
```

The host's Python is **3.12**; the container's is **3.11**. This is the whole point of the reference: pin a specific runtime version inside a container, independent of the host distro, with no registry access at runtime.

For a deeper poke, drop into a shell inside the container (it's Alpine, so `sh` not `bash`):

```bash
docker exec -it container-app sh
# inside: python --version, pip list, cat /app/app.py, exit
```

#### Watch live logs

```bash
journalctl -u container-app -f
```

Each request to `:8080` produces a Flask log line. `Ctrl+C` to stop.

✅ **Phase 1 complete.** The device is running `hello-flask:py311` and serving HTTP on port 8080 — fully offline. You can stop here for a basic deploy, or continue to Phase 2 to demonstrate runtime updates.

---

## Phase 2 — Swap to a different container at runtime

In Phase 2, the device is already running from Phase 1. You'll swap to a **different** container image at runtime — no rebuild, no reflash, no re-provision. The reference ships a `container-swap` helper for this; it pulls a target image, updates the active-image env file, and restarts the systemd service in place.

The image used as the swap target is `docker.io/peridionick/hello-flask-new:py314` — Python 3.14 + Flask 3.1.3 (one major version up from the Phase 1 baked-in 3.11 + 3.0.3). The device needs internet access for the initial pull. The originally-baked image stays cached on the var partition throughout, so the rollback at the end of this phase works **fully offline**.

### Confirm the swap script is available

Still SSH'd into the device:

```bash
which container-swap
# /usr/local/bin/container-swap

container-swap
# Usage:
#   container-swap <image:tag>   Pull and run a new image.
#   container-swap reset         Restore the factory default (...)
```

### Swap to the updated image

```bash
container-swap docker.io/peridionick/hello-flask-new:py314
```

Expected output (timing varies with network speed; pull is typically 30–90 seconds):

```
Pulling docker.io/peridionick/hello-flask-new:py314...
py314: Pulling from peridionick/hello-flask-new
...
Status: Downloaded newer image for docker.io/peridionick/hello-flask-new:py314
Restarting container-app.service...
Now running: docker.io/peridionick/hello-flask-new:py314
```

### Verify the new container is running

```bash
docker ps
# CONTAINER ID  IMAGE                                              ...  NAMES
# abc123def456  docker.io/peridionick/hello-flask-new:py314        ...  container-app
```

The image column should show `hello-flask-new`, not `hello-flask`.

```bash
docker exec container-app python --version
# → Python 3.14.X   (was Python 3.11.X before the swap)

docker exec container-app python -c "import flask; print(flask.__version__)"
# → 3.1.3            (was 3.0.3 before the swap)
```

From any machine on the LAN, hit the endpoint:

```bash
curl http://<device-ip>:8080
```

The page now contains the **UPDATED** badge and reports `Container Python: 3.14.X` and `Flask version: 3.1.3`. Both the original (Python 3.11 + Flask 3.0.3) and the swap target (Python 3.14 + Flask 3.1.3) are now resident on the device:

```bash
docker images
# REPOSITORY                              TAG     ...  SIZE
# peridionick/hello-flask-new   py314   ...  ~75MB
# peridionick/hello-flask       py311   ...  ~75MB
```

### Confirm the swap persists across reboots

```bash
cat /var/lib/container-app/active-image.env
# CONTAINER_IMAGE=docker.io/peridionick/hello-flask-new:py314

reboot
```

After the device comes back up and you SSH in again:

```bash
curl http://<device-ip>:8080 | grep "Container Python"
# Still → Python 3.14.X
```

### Roll back to the originally-baked image

```bash
container-swap reset
```

`reset` does not pull anything — the original image is still cached locally on the var partition, so this step works even without network access. Expected output:

```
Resetting to factory default: docker.io/peridionick/hello-flask:py311
Restarting container-app.service...
Now running: docker.io/peridionick/hello-flask:py311
```

Confirm:

```bash
curl http://<device-ip>:8080 | grep "Container Python"
# → Python 3.11.X (back to the original)

docker exec container-app python --version
# → Python 3.11.X
```

### How it works under the hood

- The systemd unit reads `${CONTAINER_IMAGE}` from `/var/lib/container-app/active-image.env`.
- `container-swap <image:tag>` runs `docker pull`, rewrites that env file, and `systemctl restart`s the service.
- The env file lives under `/var` (not `/etc`, which is read-only on Avocado), so swaps persist across reboots.
- `container-swap reset` rewrites the env file back to the factory default — the same image that was baked into the var partition at build time, so it's always available offline.
- To swap to your own image: `container-swap docker.io/<your-org>/<your-image>:<tag>`.
- Each successful swap leaves the previous image cached locally; you can flip back and forth without re-pulling. Storage is bounded by the var partition (2048 MB in this reference), so very long swap chains will eventually need `docker image prune` to reclaim space.

✅ **Phase 2 complete.** The device just demonstrated a full runtime-update lifecycle: pulled a new image at runtime, swapped to it, persisted the swap across reboot, and rolled back to the original image without network access.

---

## Debugging

### `avocado build` fails with `fwup: file size assertion failed`

The var partition cap in the active stone manifest is too small for the seeded Docker image. The reference bumps `raspberrypi4` to 2048 MB; this error means either you're on a different target with no per-target manifest, or the cap still isn't large enough. Bump the `var` partition `size` in `stone/<target>/stone-<target>.json`. See **Customize → Adjust the var partition size**.

### `avocado build` fails with "manifest file not found"

The reference ships a stone manifest only for `raspberrypi4`. Add `stone/<target>/stone-<target>.json` for any other target — see **Customize → Adjust the var partition size**.

### `avocado build` fails during the registry pull

- Local Docker daemon not running. Start Docker Desktop (or `sudo systemctl start docker`).
- Docker Hub rate-limited. Run `docker login` from your shell before `avocado build`; the SDK container reuses your host's credentials.
- Proxy or DNS issue. Confirm `curl -I https://registry-1.docker.io/v2/` works from your shell.

### Container service fails to start on the device

```bash
journalctl -u container-app.service -b --no-pager | tail -30
```

The most useful diagnostic for the container itself:

```bash
docker logs container-app
```

Common causes: image missing locally (re-run `avocado build` and re-provision), port 8080 already bound (change the `-p` flag in the systemd unit), kernel module missing for Docker's bridge networking (the `docker` extension declares `kernel-module-bridge`, `kernel-module-br-netfilter`, and `kernel-module-veth` — keep them if you fork).

## Customize

### Change the image permanently

For changes that should land in the next provisioned image (rather than only at runtime), edit `docker_images` in `avocado.yaml`:

```yaml
docker_images:
  - image: docker.io/<your-org>/<your-image>
    tag: <your-tag>
```

Then update the factory default in two places so the systemd unit and `container-swap reset` agree:

- `overlay/app/usr/lib/tmpfiles.d/container-app.conf` — the seeded `CONTAINER_IMAGE=` line
- `overlay/app/usr/local/bin/container-swap` — the `DEFAULT_IMAGE=` shell variable

Rebuild:

```bash
avocado build
avocado provision -r dev
```

### Change the served page

The page content lives inside the Docker image, not in this reference. Edit the image source (Dockerfile + `app.py`), publish a new tag to the registry, bump the tag in `avocado.yaml`, then rebuild.

### Change the listening port

In `overlay/app/etc/systemd/system/container-app.service`:

```
-p <new-host-port>:8080
```

The `:8080` on the right is the container's Flask port; don't change it unless you also edit `app.py` in the image source.

### Adjust the var partition size

The reference ships `stone/raspberrypi4/stone-raspberrypi4.json` with the var partition at 2048 MB. The relevant block:

```json
{
  "name": "var",
  "image": "var",
  "size": 2048,
  "size_unit": "mebibytes",
  "expand": "true"
}
```

Bump `size` for larger images. `expand: "true"` means the partition still grows on first boot to fill the SD card, so this value mostly affects build-time allocation.

To support another target, add `stone/<target>/stone-<target>.json`:

1. Pull the BSP's default manifest out of the SDK container:
   ```bash
   docker run --rm docker.io/avocadolinux/sdk:2024-edge \
     cat /opt/avocado-sdk/stone/stone-<target>.json \
     > stone/<target>/stone-<target>.json
   ```
2. Edit the `var` partition's `size` upward.
3. If you also need a custom `bootfiles/config.txt`, drop it at `stone/<target>/bootfiles/config.txt`. Unmodified files fall through to the BSP defaults.

The avocado.yaml `stone_manifest:` and `stone_include_paths:` lines are templated with `{{ avocado.target }}`, so per-target convention works automatically.

### Add Docker daemon configuration

Edit `overlay/docker/etc/docker/daemon.json`. The default is `{}`; add daemon-level config (insecure registries, log drivers, etc.) as needed.

### Pull from a private registry

Run `docker login <registry>` from your shell before `avocado build`. The SDK container reuses your host's Docker credentials.

