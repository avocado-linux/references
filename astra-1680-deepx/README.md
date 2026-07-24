---
language: C++
targets:
  - grinn-astra-1680-sbc
topics:
  - npu
  - ai-inference
  - object-detection
  - computer-vision
  - deepx
---

# astra-1680-deepx

Real-time AI inference on the **DeepX M1 NPU** attached to a Grinn Astra SL1680 SBC: the DeepX PCIe kernel driver, the DXRT runtime, sample models, and a Qt5 YOLO object-detection demo that draws detections over a live camera feed on a Weston/Wayland display — all cross-compiled natively as Avocado extensions, no containers.

- Brings the DeepX M1 NPU up from source: the PCIe kernel driver (`dx_dma`, `dxrt_driver`) and the DXRT runtime + `dxrt.service` are compiled in the SDK and shipped as extensions
- A `dev-deepx` runtime composes the full stack — driver, runtime, sample models, and the Qt example — on top of a base Weston desktop; a lighter `dev` runtime brings up just the display for board bring-up
- Qt5/QML example runs live YOLO object detection on the NPU and renders bounding boxes over the camera feed via a Weston kiosk session
- Everything cross-compiles in the Avocado SDK against `grinn-astra-1680-sbc`: kernel modules, the DXRT C++ runtime, OpenCV, and the Qt application
