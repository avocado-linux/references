---
language: C++
targets:
  - rzv2n-sr-som
topics:
  - vision
  - drp-ai
  - npu
  - gstreamer
  - wayland
icon: icon.png
---

# RZ/V2N DRP-AI3 YOLOv3 Object Detection

Object detection demo for the SolidRun RZ/V2N HummingBoard SoM. Pulls frames from a looping video file (default) or the on-board IMX678 MIPI CSI-2 camera, runs YOLOv3 (Darknet/COCO) inference on the **on-chip DRP-AI3 accelerator** using Renesas's TVM-compiled model from the RZ/V2N AI SDK v6.30, and renders the annotated feed full-screen on Wayland/Weston.

- Video-file or camera input via GStreamer (H.264 decode via libav, software)
- YOLOv3 object detection compiled for DRP-AI3 (Mera2 + Apache TVM runtime)
- Seek-on-EOS loop so a short clip plays indefinitely
- OpenCV bounding-box overlay drawn per frame, pushed to `waylandsink`
- `fetch-model.sh` pulls the DRP-AI3 YOLOv3 bundle from Renesas's `rzv_ai_sdk` v6.00 release; `fetch-video.sh` grabs a sample clip
- Auto-starts after Weston via systemd

**Camera path is currently disabled**: the SolidRun rzg2l-cru / IMX678 driver misreports its V4L2 format at 4K (claims `3840×2160 8-bit RGGB`, actually streams `1920×2160 12-bit-in-16-bit-BE Bayer` at half the advertised horizontal resolution). Frames decode as orange/cyan vertical stripes. The video-file path is the default until that driver bug is fixed.
