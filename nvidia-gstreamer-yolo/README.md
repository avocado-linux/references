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

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> NVIDIA GStreamer YOLO Object Detection

A reference runtime that demonstrates real-time object detection on an NVIDIA Jetson Orin Nano using a USB (UVC) camera, GStreamer, and YOLO11 with GPU-accelerated inference via **TensorRT**. The app serves the annotated video feed as an MJPEG stream with a web dashboard.

This is the "roll your own GPU inference" reference: a plain GStreamer capture pipeline feeds frames into a Python app that runs the TensorRT engine itself — you can read the entire detect → infer → NMS → draw loop in one file. (For the batteries-included NVIDIA SDK path — a multi-model `nvinfer` pipeline with tracking and pose — see the `nvidia-deepstream` reference instead.)

- Capture video from a UVC camera and run YOLO11n object detection on the Jetson GPU
- Ship a **prebuilt FP16 TensorRT engine** so the app runs immediately on first boot — no compile wait
- Self-heal: if the embedded engine can't load (e.g. a TensorRT version bump) or the model is swapped, rebuild the engine from the ONNX on-device automatically
- Run inference directly from Python via the TensorRT runtime API (`execute_async_v3`)
- Serve a live MJPEG stream with bounding boxes drawn on detected objects
- Expose JSON API endpoints for detections and device metrics
- Auto-select the best GStreamer capture pipeline (GPU or CPU decode) based on available hardware
