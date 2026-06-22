# Getting started — imx8mp-npu-pose

Prerequisites: Avocado CLI (`>=0.26.0`), Docker, a `ucm-imx8m-plus` board with a
USB webcam, and the eIQ ML stack in your feed (`packagegroup-avocado-imx-ml`). A
display is optional — the browser preview works headless.

## 1. Fetch the model + calibration images

```sh
./fetch-model.sh          # MoveNet SavedModel -> app/build/movenet, ~40 images -> app/build/rep
```

For real accuracy, drop frames with people (in your scene's lighting/poses) into
`app/build/rep/` and re-run the build.

## 2. Build (quantization happens here, in the SDK)

```sh
avocado build
```

`app-compile.sh` runs in the SDK: it `uv pip install`s TensorFlow 2.16, runs
`quantize-model.py` to produce a per-tensor INT8 `movenet_int8.tflite`, and
`app-install.sh` copies it into the app extension. TensorFlow is not shipped to
the target.

## 3. Provision

```sh
avocado provision -r dev      # then flash per your board (uuu-emmc / sd)
```

## 4. View it

- **Browser (headless or not):** open `http://<board-ip>:8080/` — live camera
  with the skeleton overlaid.
- **HDMI display:** if a KMS display + weston are up, the skeleton renders there
  automatically too.
- **Journal:** `journalctl -fu imx8mp-npu-pose` shows FPS + visible-keypoint count.

Confirm the NPU is doing the work:

```sh
lsmod | grep galcore 2>/dev/null; ls -l /dev/galcore     # NPU present
journalctl -u imx8mp-npu-pose | grep -i "vx delegate"    # error_during_* = 0
```

## 5. NPU vs CPU

```sh
systemctl set-environment USE_NPU=1 && systemctl restart imx8mp-npu-pose   # NPU
systemctl set-environment USE_NPU=0 && systemctl restart imx8mp-npu-pose   # CPU
```

The INT8 MoveNet should run materially faster on the NPU. Equal FPS ⇒ the model
fell back to CPU (check the journal for VX-delegate errors / per-op fallback).

## Troubleshooting

- **No skeleton, "0/17 keypoints":** no person in frame, or `SCORE_THRESH` too
  high (`systemctl set-environment SCORE_THRESH=0.2`). Stand back so your whole
  body is in the (square-cropped) frame.
- **Wrong camera:** auto-detect picks the first real capture node; override with
  `CAMERA_DEVICE=/dev/videoN`.
- **Skeleton offset/mirrored:** coordinate mapping assumes the square crop — if
  you change `PREVIEW_SIZE` or the crop, re-check the mapping in `on_draw`.
- **Black screen on HDMI:** that's the display path, not pose — see the
  `imx8mp-npu-nnstreamer` notes (needs a KMS display + weston). The web preview
  sidesteps it entirely.
