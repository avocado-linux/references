# imx8mp-npu-nnstreamer

Live **MobileNet INT8** camera classification offloaded to the **i.MX8M Plus
NPU** (Vivante VIP9000, ~2.3 TOPS), built with **NNStreamer** + the TensorFlow
Lite **VX delegate**, with **in-SDK INT8 quantization**.

Validated target: **`ucm-imx8m-plus`** (CompuLab UCM-iMX8M-Plus SOM, NXP BSP).
Any NXP-BSP i.MX8MP board with a camera + display should work.

## What it demonstrates

The NPU offload chain:

```
v4l2 camera
  -> nnstreamer tensor_converter
  -> tensor_filter (TFLite, INT8 model, custom=Delegate:External,
       ExtDelegateLib:libvx_delegate.so)
  -> tflite-vx-delegate -> tim-vx -> imx-gpu-viv (libOpenVX/libVSC)
  -> galcore.ko -> Vivante VIP NPU
```

A `tensor_sink` callback reads the model output, prints the top-1 label + FPS
to the journal, and overlays it on the live camera view (`waylandsink`).

**NPU vs CPU comparison** is one knob — `USE_NPU=1` (default) loads the VX
delegate; `USE_NPU=0` runs the same INT8 model on the CPU. Watch the FPS in
`journalctl -u imx8mp-npu-nnstreamer`.

## Why this board / BSP

The NPU stack is version-coupled: `tim-vx` / `tflite-vx-delegate` are written
against NXP's `imx-gpu-viv 6.4.11` (libOpenVX) + a matched `galcore`. This board
runs the **NXP BSP**, so that matched stack is present out of the box — the eIQ
packages just had to be built into the feed (`packagegroup-avocado-imx-ml`, see
`kas/vendor/nxp.yml`). On a community-BSP i.MX8MP (e.g. the imx8mp-evk's default
freescale BSP, gpu-viv 6.2.4) this delegate path does not work.

## Quantization

The VIP NPU accelerates **per-tensor INT8** TFLite models; float / per-channel /
unsupported ops silently fall back to the CPU. `quantize-model.py` (run in the
SDK by `app-compile.sh`) does post-training quantization of MobileNetV2 with:

- `inference_input/output_type = uint8` and the `[0,255]->[-1,1]` rescale folded
  into the graph, so the pipeline feeds raw uint8 RGB straight from
  `tensor_converter` — no normalization node.
- `_experimental_disable_per_channel = True` → per-tensor weights for the NPU.

TensorFlow is a **build-time-only** SDK dependency (installed via `uv pip` into
an ephemeral venv); it is never shipped to the target.

## Layout

```
avocado.yaml         runtime + app extension + SDK compile hooks
fetch-model.sh       fetch representative calibration images (run first)
quantize-model.py    PTQ MobileNetV2 -> INT8 (uint8 I/O, per-tensor)
app-compile.sh       SDK hook: pip install TF, run the quantizer
app-install.sh       copy model + labels into the extension sysroot
app-clean.sh         drop build artifacts
app/overlay/usr/local/bin/app.py                         the NNStreamer app
app/overlay/usr/lib/systemd/system/imx8mp-npu-nnstreamer.service
```

See [getting_started.md](getting_started.md) to build and run it.

## Notes / tuning

- Defaults to a **USB UVC webcam** at `/dev/video0` (`kernel-module-uvcvideo`).
  For the SOM's MIPI-CSI cameras, add a `media-ctl` init step (see the
  `rzv2n-drpai-yolo` reference's `v4l2n-init-*.sh` for the pattern) and point
  `CAMERA_DEVICE` at the resulting node.
- Exact GStreamer plugin splits and the `textoverlay`/caps wiring may need minor
  adjustment for your camera's formats — `app.py` prints the full pipeline at
  startup to make this easy to iterate.
