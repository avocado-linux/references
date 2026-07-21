---
language: C++
targets:
  - jetson-orin-nano-devkit
  - imx8mp-evk
  - imx93-evk
topics:
  - executorch
  - machine-learning
  - vision
  - segmentation
  - cross-compilation
  - edge-ai
---

# executorch-segmentation — live semantic segmentation on the portable ExecuTorch runtime

A single ~few-hundred-KB C++ binary runs **DeepLabV3-MobileNetV3** on a USB camera
entirely on the CPU, classifying all 21 PASCAL VOC classes per pixel and streaming
the colorized mask, blended over the live video, to your browser.

The point is the runtime and the workflow, not the model. Inference runs on the
**portable ExecuTorch runtime linked statically into the binary** — no PyTorch,
no Python, no accelerator on the device. The exported `.pte` and the binary are
**identical across an NVIDIA Jetson Orin Nano (aarch64), an NXP i.MX8M Plus
(Cortex-A53), and an NXP i.MX93 (Cortex-A55)**: one artifact, many boards.

What Avocado adds on top of ExecuTorch: the ExecuTorch runtime is a **first-class
package in the Avocado feed**, the app is **cross-compiled and deployed to real
hardware with one CLI**, and the whole thing is a reproducible, OTA-updatable OS
image — not a laptop demo.

## How it works

```
USB camera ─▶ OpenCV (resize 256² + normalize) ─▶ segmentation.pte ─▶ per-pixel
                                                   (DeepLabV3, portable CPU)   argmax
           browser ◀─ MJPEG ◀─ blend(mask, frame) ◀─ VOC colorize ◀────────────┘
              http://<board-ip>:8080/
```

- **Portable-only, statically linked** — the `.pte` is lowered with `to_edge()`
  and no backend partitioner (matching Avocado's portable-only `executorch`
  package), and the runtime archives are linked into the binary. There is no
  `executorch` package on the device.
- **Feed-only, pip-free build** — the model is exported once offline and
  committed, so `avocado build` is just a fast C++ cross-compile linking
  `executorch-*` + `opencv` from the feed. No uv, no torch, no network.
- **Zero third-party runtime deps** — the web view is a hand-rolled MJPEG server
  on POSIX sockets; nothing is fetched at build time.

Later phases can move export into the build (via feed-hosted torch), add
accelerated backends (Jetson CUDA, i.MX93 Ethos-U), or add more modalities.

## Usage

See `getting_started.md`.
