# Getting Started with x86 RTX GPU Inference

This reference exercises a discrete NVIDIA RTX GPU on an Intel x86-64 host two
ways — host-native TensorRT-RTX (`-r native`) and a CUDA container via the
NVIDIA Container Toolkit / CDI (`-r docker`).

## Prerequisites

- **Hardware:** an Intel x86-64-v3 (Haswell+/Raptor Lake, AVX2) system with a
  discrete NVIDIA RTX 40- or 50-series GPU. Validated on a Neousys Nuvo-9000
  (i9-14900) with an RTX 4000 SFF Ada; a LattePanda Sigma board BSP is also
  available.
- **[Avocado CLI](https://docs.peridio.com)** `>= 0.41.0` (matches
  `cli_requirement` in `avocado.yaml`; the `docker_images` pre-seed used by the
  docker runtime needs it).
- **A board must be selected.** The board BSP is pulled as
  `avocado-bsp-{{ avocado.target.board }}` and supplies the NVIDIA driver stack
  (kernel modules, `libcuda`, `nvidia-smi`, GSP firmware). Pass
  `--target-board nuvo-9000` or `--target-board lattepanda-sigma`. Without a
  board the name falls back to the target and resolves the generic
  `avocado-bsp-intel-x86-64-v3`, which carries no NVIDIA driver — the image
  builds but both runtimes fail at `nvidia-smi`/`libcuda`.
- **Extensions must be resolvable** in your feed (or built locally):
  - both runtimes → `avocado-bsp-<board>`
  - native runtime → `avocado-ext-nvidia-tensorrt-rtx`
  - docker runtime → `avocado-ext-nvidia-container-toolkit` (the docker engine is
    inlined as the `docker` extension; the `docker` feed package must resolve)
- **Licensing:** TensorRT-RTX (native runtime) and the `nvidia/cuda` image
  (docker runtime) are NVIDIA proprietary software — confirm your redistribution
  terms before shipping an image that bundles them.

## Initialize

```bash
avocado init --reference x86-rtx my-rtx-inference
cd my-rtx-inference
```

## Install

Resolve extensions and SDK packages for the target and board:

```bash
avocado install -f --target-board nuvo-9000
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
  `app/build/model.onnx`; `app-install.sh` stages them; the
  `avocado-ext-nvidia-tensorrt-rtx` extension supplies `libtensorrt_rtx`, the
  Python bindings, and the CUDA runtime libraries.
- **docker** — `docker_images` pulls `nvidia/cuda` into the target `/var` at
  build time (needs `nativesdk-docker`, already in the SDK set); the
  `avocado-ext-nvidia-container-toolkit` extension supplies `nvidia-ctk`, the
  CDI `daemon.json`, and the boot-time CDI-generate service.

## Deploy

Pick a runtime and provision. The `dev` permissions profile (see `avocado.yaml`)
bakes an empty root password into **both the rootfs and the initramfs**, so root
can log in over SSH *and* at the console/emergency shell if boot fails — **demo
only**; use a real hashed password for production.

```bash
avocado provision -r native    # host-native TensorRT-RTX dashboard
# or
avocado provision -r docker    # GPU inside a CUDA container via CDI
```

## Verify

### native runtime

Point a browser (or `curl`) at the device on port 8080:

```console
$ curl -s http://<device-ip>:8080/api/stats
{
  "gpu": "NVIDIA RTX 4000 SFF Ada Generation",
  "trt_version": "1.5.0.114",
  "engine_build_ms": 812.4,
  "engine_cached": false,
  "infers_per_sec": 14200.0,
  "mean_latency_ms": 0.061,
  "status": "running",
  "total_infers": 128000
}
```

`"status": "running"` with a non-zero `infers_per_sec` confirms the full path
works: driver → CUDA → TensorRT-RTX engine build → GPU execution. The HTML view
at `http://<device-ip>:8080/` shows the same numbers, auto-refreshing.

You can also run the extension's platform self-test directly over SSH:

```console
$ nvidia-inference-selftest
[ OK ] GPU visible to driver: NVIDIA RTX 4000 SFF Ada Generation, 595.84, 20475 MiB
[ OK ] tensorrt_rtx 1.5.0.114 imported
[ OK ] engine built and deserialized (2 IO tensors)
PLATFORM VALIDATED: driver + CUDA + TensorRT-RTX are functional.
```

If `status` is `error`, read `error` in `/api/stats` or
`journalctl -u app.service` — a missing driver shows up as an `nvidia-smi` /
`libcuda` failure, a runtime-lib gap as an import error.

### docker runtime

The `gpu-container.service` oneshot runs `nvidia-smi` inside the pre-seeded
`nvidia/cuda` container. Check it over SSH:

```console
$ systemctl status nvidia-cdi-generate.service   # active (exited) — wrote /var/run/cdi/nvidia.yaml
$ nvidia-ctk cdi list                            # nvidia.com/gpu=all, nvidia.com/gpu=0
$ journalctl -u gpu-container.service            # nvidia-smi table -> GPU seen inside the container
$ docker run --rm --device nvidia.com/gpu=all docker.io/nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
```

Seeing the `nvidia-smi` GPU table from inside the container confirms the full
CDI path: driver → CDI spec → docker injects the GPU into the container. If it
fails, check `nvidia-cdi-generate.service` (spec generation) and that
`/etc/docker/daemon.json` has `features.cdi: true`.

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
  Delete it to force a rebuild after changing the model or GPU.
- **Port:** set `APP_PORT` in `app.service`.

For the **docker** runtime:

- **Run real CUDA, not just `nvidia-smi`:** bump the `docker_images` tag in
  `avocado.yaml` (and the matching tag in `gpu-container.service`) to a
  `-runtime-` or `-devel-` image (e.g. `13.0.1-runtime-ubuntu24.04`, matching the
  595.84 driver's CUDA 13) and change the container command to your workload.
  Keep the two tags in sync — the service runs exactly what was pre-seeded.
- **Your own image:** point `docker_images` at any registry image; it is pulled
  into `/var/lib/docker` at build time so the device needs no network at runtime.
- **Long-running container:** change `gpu-container.service` from `Type=oneshot`
  to a normal service (drop `RemainAfterExit`, run your serving process) if you
  want a persistent GPU workload instead of a one-shot check.
