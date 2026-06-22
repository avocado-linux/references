# Getting started — imx8mp-npu-nnstreamer

Prerequisites: the Avocado CLI (`>=0.26.0`), Docker, a `ucm-imx8m-plus` board
with a USB webcam and an HDMI/LVDS/MIPI display attached, and the eIQ ML stack
built into your feed (`packagegroup-avocado-imx-ml`).

## 1. Fetch calibration images

INT8 post-training quantization needs a small set of representative inputs:

```sh
./fetch-model.sh          # ~50 images into app/build/rep/ (gitignored)
```

For meaningful accuracy, replace these with images representative of your actual
scene (drop `.jpg` files into `app/build/rep/`).

## 2. Build (quantize happens here, in the SDK)

```sh
avocado build
```

`app-compile.sh` runs inside the SDK container: it `uv pip install`s
TensorFlow 2.16 (build-time only — picks the right wheel for your SDK's arch,
x86_64 or aarch64), runs `quantize-model.py` to produce a per-tensor INT8
`mobilenet_v2_int8.tflite` + `labels.txt`, and `app-install.sh` copies them into
the app extension.

## 3. Provision

```sh
avocado provision -r dev          # then flash per your board (uuu-emmc / sd)
```

## 4. On the target

The `imx8mp-npu-nnstreamer.service` starts automatically after weston. You
should see the live camera on the display with a top-1 label + FPS overlay.

Watch the classifier + FPS:

```sh
journalctl -fu imx8mp-npu-nnstreamer
```

Confirm the NPU is actually doing the work:

```sh
lsmod | grep galcore          # NPU/GPU driver loaded
ls -l /usr/lib/libvx_delegate.so
```

## 5. NPU vs CPU

Edit the service (or override the env) to flip the backend and compare FPS:

```sh
# NPU (default)
systemctl set-environment USE_NPU=1 && systemctl restart imx8mp-npu-nnstreamer
# CPU — same INT8 model, no delegate
systemctl set-environment USE_NPU=0 && systemctl restart imx8mp-npu-nnstreamer
```

The INT8 model on the VIP NPU should run materially faster than on the CPU. If
the NPU FPS is *not* higher, the model likely fell back to CPU — usually because
an op isn't per-tensor INT8 (re-check the quantization knobs in
`quantize-model.py`) or `libvx_delegate.so` failed to load (check the journal).

## Troubleshooting

- **No camera**: `v4l2-ctl --list-devices`; set `CAMERA_DEVICE` in the service.
  MIPI-CSI cameras need a `media-ctl` init first (see README notes).
- **Black screen**: confirm `weston` is running (`systemctl status weston`) and
  the `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` in the service match your weston setup.
- **Pipeline errors**: `app.py` prints the full pipeline at startup; run it by
  hand over SSH to iterate on caps/plugin names for your camera.
