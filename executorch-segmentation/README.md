---
language: C++
targets:
  - jetson-orin-nano-devkit
  - imx8mp-evk
  - imx93-evk
  - imx93-frdm
topics:
  - executorch
  - vision
  - segmentation
  - machine-learning
  - cross-compilation
---

# ExecuTorch Semantic Segmentation

Live semantic segmentation on the portable ExecuTorch CPU runtime. A single
cross-compiled C++ binary runs a DeepLabV3-MobileNetV3 model on a USB camera,
classifies every pixel into 21 PASCAL VOC classes, and streams the colorized
mask blended over the live video to a browser — with no accelerator, no
PyTorch, and no Python on the device.

- Runs a PyTorch model on-device through the ExecuTorch runtime, linked
  statically into one self-contained binary.
- Ships the model as a committed, portable `.pte`, so `avocado build` is a fast,
  pip-free C++ cross-compile against the ExecuTorch runtime from the Avocado feed.
- The same binary and model run unchanged across NVIDIA Jetson (aarch64) and NXP
  i.MX (Cortex-A53 / Cortex-A55) targets.
- Serves a live MJPEG dashboard from a dependency-free web server built on POSIX
  sockets — no third-party HTTP library.
