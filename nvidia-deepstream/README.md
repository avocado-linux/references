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
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> NVIDIA DeepStream

A native Avocado reference that runs NVIDIA DeepStream 7.1 on Jetson Orin hardware — no containers. A USB camera feeds a DeepStream GStreamer pipeline that detects and tracks people, extracts a body skeleton and per-hand finger keypoints, counts ROI dwell time, and serves the annotated video as an MJPEG stream with a web dashboard.

- DeepStream 7.1 runs entirely from Avocado sysext extensions — no Docker, no `nvcr.io` pulls
- The pipeline is split across five cohesive extensions (runtime / models / engines / config / app) so each kind of change ships only the bytes that changed over OTA — see [Extension layout](#extension-layout)
- Prebuilt TensorRT FP16 engines (PeopleNet + MoveNet + YOLOX-Hand + Hand-Landmark) ship read-only in the `vision-engines` extension and are memory-mapped on load — no on-device compile, no var-partition staging
- Multi-class detection (Person / Bag / Face) with persistent tracker IDs from NvDCF
- Single-person pose: 17 COCO keypoints (head, shoulders, elbows, wrists, hips, knees, ankles) per detected person, rendered as a skeleton via `nvdsosd`
- Per-hand finger tracking: a YOLOX-BHH secondary GIE finds hands inside each person, a MediaPipe Hand Landmark tertiary GIE emits 21 keypoints per hand (wrist + 4 joints per finger), colored by handedness
- ROI dwell timers and entry counters; bounding box and skeleton recolour when the person enters the zone
- Live MJPEG stream with all overlays burned in by the pipeline (no client-side rendering), plus a JSON stats endpoint and a toggleable HTML dashboard (skeletons / hands / zones independently)

## Extension layout

Rather than one monolithic application extension, the vision pipeline is composed of five
extensions, each with a single reason to change. systemd-sysext merges them into one unified
`/usr` (and confext into `/etc`) at boot, so the split is invisible to the running app — but it
means an OTA only re-ships the layer you actually touched. There is no inter-extension dependency
mechanism in systemd; the `dev` runtime's extension list in `avocado.yaml` is the contract that
all five are composed together.

| Extension | Type | Holds | Re-ships when… | Rough size |
|---|---|---|---|---|
| `vision-runtime` | sysext + confext | DeepStream, pyds, TensorRT, CUDA/cuDNN, GStreamer NV plugins, `uvcvideo`, Python + bindings + Flask (your **dependencies**) — the confext carries the packages' `/etc/ld.so.conf.d` entries so `ldconfig` can find the DeepStream/CUDA libs | JetPack / DeepStream / CUDA bump (rare) | GB-scale |
| `vision-models` | sysext | the four ONNX files (`/usr/lib/nvidia-deepstream/models/`) | a model is retrained or swapped | ~31 MB |
| `vision-engines` | sysext | prebuilt TensorRT engines for the build target (`/usr/lib/nvidia-deepstream/engines/`) | models change, or a TRT/JetPack bump | ~19 MB |
| `vision-config` | confext | nvinfer / tracker / analytics configs (`/etc/nvidia-deepstream/`) | retuning thresholds, ROI zones, tracker profile | KB |
| `vision-app` | sysext | `app.py`, its systemd unit, the preflight script (your **code**) | business-logic iteration (frequent) | KB |

The payoff: editing a threshold re-ships a kilobyte confext; editing `app.py` re-ships a kilobyte
sysext; retraining a model re-ships tens of megabytes; and the gigabytes of CUDA/DeepStream only
move when you actually upgrade the platform.

The lower layers (`vision-models`, `vision-engines`, `vision-config`) carry an
`on_merge: systemctl try-restart vision-app.service` hook so an OTA of just those layers restarts
the app to pick up the new artifacts without a reboot. `vision-app` owns and starts the service
itself.
