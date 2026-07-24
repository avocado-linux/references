# Getting Started with Jetson TensorRT GPU Inference

This reference exercises the integrated NVIDIA GPU on a Jetson two ways —
host-native TensorRT (`-r native`) and an L4T container via upstream docker +
the NVIDIA Container Toolkit `nvidia` runtime (`-r docker`) — on the 2026 (wrynose /
JetPack 7) release.

## Prerequisites

- **Hardware:** a supported Jetson. Validated first on **Jetson AGX Thor**
  (tegra264, JetPack 7.2 / L4T r39.2); `jetson-agx-orin` and
  `jetson-orin-nano` (tegra234) are also supported off the same 2026 feed.
- A UART-to-USB adapter and a USB-C cable for the recovery-mode flash.
- **[Avocado CLI](https://docs.peridio.com)** `>= 0.41.0` (the `docker_images`
  pre-seed used by the docker runtime needs it).
- **The GPU driver is in the BSP.** Unlike the x86 dGPU reference, you do **not**
  add a driver extension — `avocado-bsp-jetson-<target>` already ships the
  integrated Tegra GPU stack (nvgpu, `nvidia.ko`, tegra-dce, tsecriscv,
  `libcuda`, `tegra-libraries-cuda`) and the GSP firmware.
- **Feed packages must resolve** for the target:
  - native runtime → `python3-tensorrt` + `tensorrt-core` + `cuda-cudart` +
    `cuda-libraries`. **On a brand-new SoC (e.g. Thor/tegra264) confirm TensorRT
    is published in the 2026 feed for that arch** — it is proven for Orin
    (tegra234); if it is not yet built for tegra264, the native runtime install
    will fail to resolve and you'll want the docker runtime meanwhile.
  - docker runtime → `docker` (moby v29), `nvidia-container-toolkit`,
    `tegra-configs-container-csv`
- **Licensing:** the CUDA container image (`nvcr.io/nvidia/cuda`) is
  NVIDIA proprietary software — confirm your redistribution terms before
  shipping an image that bundles it.

## Initialize

```bash
avocado init --reference jetson-trt my-jetson-inference
cd my-jetson-inference
```

Target Thor is the default. To target an Orin instead:

```bash
avocado init --reference jetson-trt --target jetson-agx-orin my-jetson-inference
```

## Install

Resolve extensions and SDK packages for the target:

```bash
avocado install -f
```

## Build

```bash
avocado build
```

`avocado build` builds only the extensions in the runtime you target (pass
`-r native` or `-r docker`; default builds all). What each runtime's build does
inside the SDK container:

- **native** — `app-compile.sh` installs `flask` + `cuda-python` into
  `app/packages/` and synthesizes a tiny demo model (`gen_model.py`) into
  `app/build/model.onnx`; `app-install.sh` stages them. `tensorrt` /
  `libnvinfer` and the CUDA runtime come from the feed packages.
- **docker** — `docker_images` pulls `nvcr.io/nvidia/cuda` into the
  target `/var` at build time (needs `nativesdk-docker`, already in the SDK
  set); the `nvidia-container-toolkit` extension supplies the `nvidia` container
  runtime + `nvidia-container-setup.service` and a `daemon.json` that registers
  the `nvidia` runtime with docker.

## Deploy

Jetson provisions over USB recovery mode (tegraflash). Pick a runtime and add
the `tegraflash` profile:

```bash
avocado provision -r native --profile tegraflash    # host-native TensorRT dashboard
# or
avocado provision -r docker --profile tegraflash    # GPU inside an L4T container (nvidia runtime)
```

Follow the USB recovery-mode prompts. The `dev` permissions profile (see
`avocado.yaml`) bakes an empty root password into **both the rootfs and the
initramfs**, so root can log in over SSH *and* at the console/emergency shell if
boot fails — **demo only**; use a real hashed password for production.

## Verify

### native runtime

Point a browser (or `curl`) at the device on port 8080:

```console
$ curl -s http://<device-ip>:8080/api/stats
{
  "gpu": "Orin",
  "trt_version": "10.16.2.10",
  "engine_build_ms": 640.2,
  "engine_cached": false,
  "infers_per_sec": 9800.0,
  "mean_latency_ms": 0.09,
  "status": "running",
  "total_infers": 88000
}
```

`"status": "running"` with a non-zero `infers_per_sec` confirms the full path
works: BSP driver → CUDA → TensorRT engine build → GPU execution. The HTML view
at `http://<device-ip>:8080/` shows the same numbers, auto-refreshing.

If `status` is `error`, read `error` in `/api/stats` or
`journalctl -u app.service` — a missing driver shows up as a `libcuda` /
`cudaGetDeviceProperties` failure, a runtime-lib gap as an `import tensorrt`
error, and a missing feed package as an unresolved-package failure at install.

### docker runtime

The `gpu-container.service` oneshot runs `nvidia-smi` inside the pre-seeded L4T
container via the `nvidia` runtime. Check it over SSH:

```console
$ systemctl status nvidia-container-setup.service   # active (exited) — wrote /run/nvidia-container-runtime/config.toml
$ docker info | grep -iA2 -i runtime                # Runtimes: ... nvidia ...
$ journalctl -u gpu-container.service               # nvidia-smi table -> GPU seen inside the container
$ docker run --rm --runtime nvidia nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04 nvidia-smi
```

Seeing the `nvidia-smi` GPU output from inside the container confirms the full
Tegra CSV-passthrough path: BSP driver → CSV mount lists → the `nvidia` runtime
mounts the GPU userspace into the container. If it fails, check
`nvidia-container-setup.service` (it writes `/run/nvidia-container-runtime/config.toml`),
that `tegra-configs-container-csv` is installed
(`ls /etc/nvidia-container-runtime/host-files-for-container.d/`), and that
`/etc/docker/daemon.json` registers the `nvidia` runtime (a bare
`docker run --runtime nvidia ...` must not fail with "unknown runtime").

To run **real TensorRT inside the container** (not just `nvidia-smi`): NVIDIA
hasn't published `l4t-jetpack` for JetPack 7, and the `-runtime` CUDA image has
no TensorRT. Use a JetPack 7 framework container that ships TensorRT (e.g.
`nvcr.io/nvidia/pytorch:<YY.MM>-py3` — confirm it has a `linux/arm64` variant for
Thor) or a `-devel` CUDA image with TensorRT installed, then run `trtexec` on a
bind-mounted model:

```bash
docker run --rm --runtime nvidia -v /usr/lib/app/models:/models:ro \
  <jp7-tensorrt-image> trtexec --onnx=/models/model.onnx --fp16
```

## Customize

- **Your own model:** drop a `.onnx` at `/usr/lib/app/models/` and set
  `APP_MODEL=/usr/lib/app/models/<your>.onnx` in `app.service` (or delete
  `gen_model.py` and commit your model into the overlay). The worker handles any
  graph with one float32 input and one float32 output; extend `app.py` for
  multi-IO or non-float models.
- **Real input data:** the worker feeds random tensors to measure throughput.
  Replace the input fill in `worker()` with your preprocessing (camera frames,
  files, a queue).
- **Engine cache:** the built engine is cached at `/var/cache/app/engine.plan`.
  Delete it to force a rebuild after changing the model, the Jetson, or the
  TensorRT version (engines are pinned to the GPU + TRT/CUDA version).
- **Port:** set `APP_PORT` in `app.service`.

For the **docker** runtime:

- **Image choice:** `docker_images` pulls
  `nvcr.io/nvidia/cuda:13.2.1-runtime-ubuntu24.04` (CUDA 13.2 == Thor's driver,
  `linux/arm64`). NVIDIA hasn't published the classic Jetson base images
  (`l4t-jetpack` tops out at r36.4.0 / JetPack 6, `l4t-cuda` at CUDA 12.6) for
  JetPack 7, so this uses the standard CUDA image; on Tegra the `nvidia` runtime
  CSV-mounts the host GPU userspace (incl. `nvidia-smi`) into it. Point
  `docker_images` at any image you can pull for `linux/arm64`.
- **Your own image:** point `docker_images` at any registry image; it is pulled
  into `/var/lib/docker` at build time so the device needs no network at runtime.
- **Long-running container:** change `gpu-container.service` from `Type=oneshot`
  to a normal service (drop `RemainAfterExit`, run your serving process) if you
  want a persistent GPU workload instead of a one-shot check.
