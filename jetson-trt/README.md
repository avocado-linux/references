---
language: Python
targets:
  - jetson-agx-thor
  - jetson-agx-orin
  - jetson-orin-nano
topics:
  - ai
  - inference
  - tensorrt
  - gpu
  - jetson
  - docker
  - l4t
---

# Jetson TensorRT GPU Inference

A GPU-inference reference for Avocado OS on NVIDIA Jetson (JetPack 7 / L4T
r39.2, 2026 release). It exercises the integrated Tegra GPU two ways,
selectable at provision time:

- **`-r native`** — host-native TensorRT: compiles an ONNX model into a
  TensorRT engine on-device, runs continuous inference on the GPU, and serves a
  live throughput/latency dashboard. Uses the standard `tensorrt` /
  `python3-tensorrt` feed packages (no dedicated extension — the Jetson BSP
  already ships the GPU driver + CUDA runtime).
- **`-r docker`** — GPU inside a container: **upstream docker** (moby v29) + the
  NVIDIA Container Toolkit's **`nvidia` runtime**, running a pre-seeded
  `nvcr.io/nvidia/cuda` image on the GPU with `docker run --runtime nvidia`.

On JetPack 7 / wrynose the container path is **no longer** the old standalone
`nvidia-docker` wrapper — it is upstream docker + `nvidia-container-toolkit`. But
unlike the x86 dGPU [`x86-rtx`](../x86-rtx) reference (CDI /
`--device nvidia.com/gpu=all`), the Tegra integrated GPU uses the toolkit's
**`nvidia` runtime in CSV-passthrough mode**: the host's GPU userspace libs are
bind-mounted into the container from `tegra-configs-container-csv`, wired up by
the package's `nvidia-container-setup.service`.

Both runtimes ride the same BSP driver stack (nvgpu + `nvidia.ko` + `libcuda`).
Highlights:

- Two GPU access models — host-native (TensorRT JIT for the actual Jetson GPU,
  e.g. Orin `sm_87`, executed with `cuda-python` buffers) and containerized
  (`docker run --runtime nvidia`)
- Container path uses upstream docker + the toolkit's `nvidia` runtime: the
  package's `nvidia-container-setup.service` writes the runtime config at boot,
  and the daemon.json registers the `nvidia` runtime — CSV passthrough mounts the
  host GPU userspace (incl. `nvidia-smi`) into the container
- The L4T image is pre-seeded into `/var` at build time (`docker_images`), so
  the device runs offline with no `nvcr.io` pull
- Native runtime serves an HTML dashboard + `/api/stats` (GPU name, engine build
  time, inferences/sec), with the engine cached to `/var`
- Testing target: Jetson AGX Thor (tegra264) first; Orin AGX / Orin Nano
  (tegra234) share the same 2026 feed and stack
