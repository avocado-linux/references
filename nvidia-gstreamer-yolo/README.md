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

## Extension layout

Rather than one monolithic application extension, the pipeline is composed of
four extensions, each with a single reason to change. systemd-sysext merges
them into one unified `/usr` (and confext into `/etc`) at boot, so the split is
invisible to the running app — but it means an OTA only re-ships the layer you
actually touched. There is no inter-extension dependency mechanism in systemd;
the `dev` runtime's extension list in `avocado.yaml` is the contract that all
four are composed together.

| Extension | Type | Holds | Re-ships when… | Rough size |
|---|---|---|---|---|
| `vision-runtime` | sysext + confext | TensorRT + CUDA Python bindings, CUDA/cuDNN, OpenCV, the NVIDIA GStreamer plugins, `uvcvideo`, Python + PyGObject + Flask (your **dependencies**) | a JetPack / TensorRT / CUDA bump (rare) | GB-scale |
| `vision-models` | sysext | the YOLO ONNX (`/usr/lib/app/models/`) | the model is retrained or swapped | ~10 MB |
| `vision-engines` | sysext | the prebuilt TensorRT engine (`/usr/lib/app/engines/`), committed directly in the overlay | the model changes, or a TRT/JetPack bump | ~8 MB |
| `vision-app` | sysext | `app.py`, `build_engine.py`, the systemd units, and the camera/detection/server tunables (Environment lines in `app.service`) — your **code** | business-logic iteration (frequent) | KB |

The payoff: editing `app.py` or retuning a threshold re-ships a kilobyte sysext;
swapping the model re-ships ~10 MB; and the gigabytes of CUDA/TensorRT only move
when you actually upgrade the platform.

The asset layers (`vision-models`, `vision-engines`) carry an
`on_merge: systemctl try-restart app.service` hook so an OTA of just those
layers restarts the app to pick up the new artifacts without a reboot.
`vision-app` owns and starts the service itself.

Unlike the `nvidia-deepstream` reference — which ships prebuilt engines as a
hard requirement with no on-device compile — this reference keeps an on-device
rebuild fallback (`build_engine.py` + `yolo-engine-build.service`): if the
committed engine is missing, fails to load after a TensorRT bump, or the model
is swapped, the device compiles one from the ONNX at boot and caches it in
`/var`.
