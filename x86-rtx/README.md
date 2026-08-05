---
language: Python
targets:
  - intel-x86-64-v3
topics:
  - ai
  - inference
  - tensorrt
  - gpu
  - vision
  - docker
  - cdi
---

# x86 RTX GPU Inference

A GPU-inference reference for Avocado OS on Intel x86-64 with a discrete NVIDIA
RTX GPU. It exercises the GPU two ways, selectable at provision time:

- **`-r native`** — host-native TensorRT-RTX: compiles an ONNX model into a
  TensorRT-RTX engine on-device, runs continuous inference on the GPU, and
  serves a live throughput/latency dashboard. Uses `avocado-ext-nvidia-tensorrt-rtx`
  (no CUDA toolkit or cuDNN in the image).
- **`-r docker`** — GPU inside a container: docker (moby 25) + the NVIDIA
  Container Toolkit via **CDI**, running a pre-seeded `nvidia/cuda` image on the
  GPU with `docker run --device nvidia.com/gpu=all`. No `libnvidia-container`.

Both runtimes ride the same driver stack (`nvidia.ko` + `libcuda` +
`/dev/nvidia*`), supplied by the board BSP selected with `--target-board`
(`nuvo-9000` or `lattepanda-sigma`). Highlights:

- Two GPU access models — host-native (TensorRT-RTX JIT for the actual GPU, e.g. Ada `sm_89`, executed with `cuda-python` buffers) and containerized (CDI)
- CDI path skips the painful `libnvidia-container` build: just `nvidia-ctk`, a CDI spec generated at boot, and `{"features":{"cdi":true}}` in the docker daemon
- The `nvidia/cuda` image is pre-seeded into `/var` at build time (`docker_images`), so the device runs offline with no registry pull
- Native runtime serves an HTML dashboard + `/api/stats` (GPU name, engine build time, inferences/sec)
- Validated hardware: Neousys Nuvo-9000 (Intel i9-14900) with an RTX 4000 SFF Ada
