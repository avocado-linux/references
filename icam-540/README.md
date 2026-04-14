---
language: Shell
targets:
  - icam-540
topics:
  - camera
  - gstreamer
  - vision
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> ICAM-540 Dev

A development runtime for the Advantech ICAM-540 with Basler Pylon camera SDK, GStreamer pipelines (including NVIDIA hardware encode/decode), OpenCV, and hardware debugging tools pre-installed. No application code — a ready-to-use environment for camera and vision development.

- Basler Pylon SDK and GStreamer plugin (`gst-plugin-pylon`) for industrial camera capture
- GStreamer pipeline with NVIDIA JPEG encode/decode and video conversion plugins
- OpenCV for image processing and computer vision development
- Hardware tools: i2c-tools, v4l-utils, usbutils for device bring-up and debugging
