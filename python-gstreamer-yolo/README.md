---
language: Python
targets:
  - jetson-orin-nano-devkit
topics:
  - vision
  - ai
  - camera
  - gstreamer
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python GStreamer YOLO Object Detection

A reference runtime that demonstrates real-time object detection on an NVIDIA Jetson Orin Nano using a USB (UVC) camera, GStreamer, and YOLO11 with GPU-accelerated inference via OpenCV DNN and CUDA. The app serves the annotated video feed as an MJPEG stream with a web dashboard.

- Capture video from a UVC camera and run YOLO11n object detection on the Jetson GPU
- Serve a live MJPEG stream with bounding boxes drawn on detected objects
- Expose JSON API endpoints for detections and device metrics
- Auto-select the best GStreamer pipeline (GPU or CPU decode) based on available hardware
