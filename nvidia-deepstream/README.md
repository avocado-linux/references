---
language: Python
targets:
  - jetson-orin-nano-devkit
  - jetson-agx-orin-devkit
topics:
  - deepstream
  - vision
  - nvidia
  - gpu
  - tracking
  - pose
  - hands
  - analytics
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> NVIDIA DeepStream

A native Avocado reference that runs NVIDIA DeepStream 7.1 on Jetson Orin hardware — no containers. A USB camera feeds a DeepStream GStreamer pipeline that detects and tracks people, extracts a body skeleton and per-hand finger keypoints, counts ROI dwell time, and serves the annotated video as an MJPEG stream with a web dashboard.

- DeepStream 7.1 runs entirely from the Avocado sysext — no Docker, no `nvcr.io` pulls
- TensorRT engines (PeopleNet + MoveNet + YOLOX-Hand + Hand-Landmark) compile on first boot and cache to the var partition for fast subsequent starts
- Multi-class detection (Person / Bag / Face) with persistent tracker IDs from NvDCF
- Single-person pose: 17 COCO keypoints (head, shoulders, elbows, wrists, hips, knees, ankles) per detected person, rendered as a skeleton via `nvdsosd`
- Per-hand finger tracking: a YOLOX-BHH secondary GIE finds hands inside each person, a MediaPipe Hand Landmark tertiary GIE emits 21 keypoints per hand (wrist + 4 joints per finger), colored by handedness
- ROI dwell timers and entry counters; bounding box and skeleton recolour when the person enters the zone
- Live MJPEG stream with all overlays burned in by the pipeline (no client-side rendering), plus a JSON stats endpoint and a toggleable HTML dashboard (skeletons / hands / zones independently)
