---
language: Shell
targets:
  - jetson-orin-nano-devkit
  - jetson-agx-orin-devkit
  - icam-540
topics:
  - gpu
  - cuda
  - tensorrt
  - deepstream
  - vision
---

# Jetson GPU Toolbox

A development runtime for Jetson Orin targets with the full L4T CUDA / cuDNN / TensorRT / DeepStream stack, the L4T runtime services (`nvstartup`, `nvphs`, `nvsciipc`) needed before `cuInit()` can succeed, NVIDIA-accelerated GStreamer plugins, the NVIDIA container runtime, a pre-built `vectorAdd` CUDA smoke test, and the connect agent for cloud telemetry.

- L4T r36.5.0 CUDA driver + runtime, cuDNN, TensorRT, DeepStream 7.1
- Pinned to the 6.6 kernel from the multi-kernel Jetson feed
- `vectorAdd` CUDA smoke test cross-compiled in the SDK and shipped at `/usr/local/bin/vectorAdd`
- `tegrastats`, `jetson_clocks`, plus the rest of `tegra-tools`
- `docker` + `nvidia-container-toolkit` for running GPU-enabled containers
- NVIDIA GStreamer plugins (`nvarguscamerasrc`, `nvvidconv`, `nvjpeg`, `nvv4l2`)
- Cloud connect via `avocado-ext-connect` (TLS provisioning + mTLS)
- Standard debug utilities (`v4l-utils`, `i2c-tools`, `usbutils`, `pciutils`, `strace`, `lsof`)
