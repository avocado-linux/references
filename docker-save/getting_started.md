# Getting Started with Docker Container — Local Tarball

Build a Docker image locally, `docker save` it to a tarball, bake the tarball into the application's sysext via `avocado build`, and load it on the device via `docker load` on sysext merge. **No registry involved at any stage.** Phase 2 demonstrates iterating on application code and pushing the update over the network with `avocado deploy`.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or a working local Docker daemon
- The latest [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A supported target from the [Support Matrix](https://docs.peridio.com/hardware/support-matrix). Verified on `raspberrypi4` and `raspberrypi5`.
- Network path from a viewing machine to the device

---

## Phase 1 — Build, deploy, and run

### Initialize

```bash
avocado init --reference docker-save docker-save
cd docker-save
```

### Install

```bash
avocado install -f
```

### Build the image

Must run before `avocado build`. Writes the tarball to `overlay/app/usr/lib/container-app/hello.tar`.

```bash
# ARM targets (Pi 4/5, Jetson, i.MX):
TARGET_PLATFORM=linux/arm64 sh build-image.sh

# x86-64 targets:
sh build-image.sh
```

### Build the runtime

```bash
avocado build
```

### Deploy

```bash
# or your supported provisioning profile (usb, emmc, etc)
avocado provision -r dev --profile sd

# QEMU 
avocado provision -r dev
```

On first boot, the app extension's `on_merge` hook runs `docker load -i /usr/lib/container-app/hello.tar` and starts `container-app.service`.

### Find the device IP

- **Serial console**: `ip addr`

### Verify

```bash
ssh root@<device-ip>          # empty root password by default

systemctl status docker.service container-app.service
# both: Active: active (running)

docker images
# hello-from-avocado    latest    ...   ~65MB

curl http://<device-ip>:8080 | grep -E 'v1\.0|Container Python'
# v1.0 badge + Python 3.10.X

docker exec container-app python --version
# Python 3.10.X

python3 --version
# Python 3.12.X  ← host
```

The host's Python is 3.12; the container's is 3.10. Same kernel, isolated userland — the load-bearing demonstration.

✅ **Phase 1 complete.** Container is running offline. Stop here or continue to Phase 2 for the update flow.

---

## Phase 2 — Update and redeploy

Application-only changes use `avocado deploy` (seconds, network push). Reserve `avocado provision` for changes outside the app (BSP, kernel, partition layout).

### Edit `app/app.py`

1. Bump `APP_VERSION` from `"1.0"` to `"2.0"`.
2. Add a `/healthz` endpoint:

```python
@app.route("/healthz")
def healthz():
    return {"status": "ok", "version": APP_VERSION}, 200
```

### Rebuild the image and runtime

```bash
TARGET_PLATFORM=linux/arm64 sh build-image.sh
avocado build
```

### Push the update

**Fast path (network deploy):**

```bash
avocado runtime deploy dev --device root@<device-ip>
```

Streams the changed sysext bytes, fires `systemd-sysext refresh` on the device, `on_merge` runs `docker load`, container restarts. Typical: seconds.

**Full path (re-flash):** use only if you also changed something outside the app.

```bash
avocado provision -r dev --profile sd
```

### Verify the update

```bash
curl http://<device-ip>:8080 | grep v2.0
# v2.0 badge

curl http://<device-ip>:8080/healthz
# {"status":"ok","version":"2.0"}   ← was 404 before Phase 2

docker exec container-app python --version
# Python 3.10.X  ← runtime unchanged
```

✅ **Phase 2 complete.** Application updated without reflashing.

---

## Debugging

### `avocado build` fails: `fwup: file size assertion failed`

Var partition cap too small. Bump `var.size` in `stone/<target>/stone-<target>.json`.

### `avocado build` fails: manifest not found

No stone manifest for your target. Add `stone/<target>/stone-<target>.json` — see **Customize → Adjust the var partition size**.

### `avocado build` fails: tarball missing

Run `sh build-image.sh` first (with `TARGET_PLATFORM` if cross-building).

### `sh build-image.sh` fails

- Docker daemon not running → start it.
- Cross-building on Linux without QEMU emulation → `docker run --privileged --rm tonistiigi/binfmt --install all`.

### Container service won't start on device

```bash
journalctl -u container-app.service -b --no-pager | tail -30
docker logs container-app
```

Common causes:

- Architecture mismatch (amd64 tarball on arm64 device) → re-run `sh build-image.sh` with correct `TARGET_PLATFORM`.
- Port 8080 in use → change `-p` in `overlay/app/etc/systemd/system/container-app.service`.
- Tarball missing in sysext → confirm `overlay/app/usr/lib/container-app/hello.tar` on the build host, rebuild, redeploy.

### After `avocado deploy`, old container still running

You probably forgot to re-run `sh build-image.sh` after editing `app.py`. The tarball didn't change, the sysext hash didn't change, and the merge was a no-op. Rebuild the image, `avocado build`, `avocado runtime deploy`.

---

## Customize

### Change app code

Edit `app/app.py`, then:

```bash
TARGET_PLATFORM=linux/arm64 sh build-image.sh
avocado build
avocado runtime deploy dev --device root@<device-ip>
```

### Change Python version

Edit `FROM python:3.10-alpine` in `app/Dockerfile`, rebuild.

### Add a dependency

Edit `app/requirements.txt`, rebuild.

### Change the listening port

Edit `app.run(..., port=8080)` in `app/app.py` AND `-p 8080:8080` in `overlay/app/etc/systemd/system/container-app.service`. Rebuild.

### Adjust the var partition size

In `stone/<target>/stone-<target>.json`:

```json
{"name": "var", "image": "var", "size": 2048, "size_unit": "mebibytes", "expand": "true"}
```

`expand: "true"` grows the partition on first boot to fill the SD card; `size` is the build-time allocation.

For a new target, copy the BSP's default manifest and bump `var.size`:

```bash
docker run --rm docker.io/avocadolinux/sdk:2024-edge \
  cat /opt/avocado-sdk/stone/stone-<target>.json \
  > stone/<target>/stone-<target>.json
```

### Add Docker daemon configuration

Edit `overlay/docker/etc/docker/daemon.json` (default: `{}`).

### Prune dangling images on device

Each redeploy leaves the previous image as a dangling reference. Periodically:

```bash
docker image prune -f
```

---

## Cleanup

Stop the container without reflashing:

```bash
ssh root@<device-ip>
systemctl stop container-app
docker rm -f container-app
```

Clean rebuild on the build host:

```bash
rm -rf .avocado .avocado-state
avocado install -f
TARGET_PLATFORM=linux/arm64 sh build-image.sh
avocado build
```
