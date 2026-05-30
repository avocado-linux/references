---
language: Python
targets:
  - raspberrypi5
  - imx8mp-evk
  - imx91-frdm
  - imx93-frdm
  - imx93-evk
  - jetson-orin-nano-devkit
topics:
  - vision
  - ai
  - opencv
  - camera
  - gstreamer
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python YOLO Object Detection

A cross-platform computer-vision reference for Avocado OS. A USB webcam feeds a GStreamer pipeline, frames run through OpenCV's DNN module with YOLOv8n (80-class COCO) on the CPU, and the annotated stream is served as MJPEG with a small Flask dashboard.

- Run the same extension on Raspberry Pi 5, NXP i.MX, and Jetson Orin Nano — no GPU or vendor accelerators required
- Stock Ultralytics YOLOv8n at 416×416, detecting 80 COCO classes via OpenCV DNN on the CPU
- Bundle the GStreamer + OpenCV vision pipeline most production systems use, with a tiny dependency surface (no CUDA, TensorRT, or DeepStream)
- Serve a live MJPEG dashboard with bounding boxes and an object counter overlay, plus a `/api/stats` JSON endpoint
