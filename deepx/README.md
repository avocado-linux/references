---
language: C++
targets:
  - grinn-astra-1680-sbc
topics:
  - ai
  - inference
  - computer-vision
  - wayland
---

# DeepX NPU Inference

A reference runtime that demonstrates real-time YOLO object detection on the DeepX NPU using a Qt5/QML Wayland application on the Grinn Astra 1680 SBC. The app ingests one or more camera streams via GStreamer, runs inference on the DeepX NPU through the `dxrt` runtime, and renders annotated bounding boxes in a fullscreen Wayland window managed by Weston.

- Run YOLOv8 object detection fully on the DeepX NPU — no GPU or CPU inference required
- Display live annotated video from one or more USB cameras in a Qt5/QML kiosk window
- Load any `.dxnn` model compiled for the DeepX NPU (YoloV8N included)
- Compose multiple camera feeds by passing additional GStreamer pipeline strings as arguments

## GStreamer Pipeline

The application is started by `qt-deepx-example.service`. The `ExecStart` line controls which cameras are used and how video frames are captured:

```ini
ExecStart=/usr/local/bin/qt_deepx_example \
  /usr/local/lib/dx-models/YoloV8N.dxnn \
  5 \
  "v4l2src device=/dev/video11 ! videoconvert ! video/x-raw,width=640,height=480,format=BGR ! videoconvert ! appsink" \
  "v4l2src device=/dev/video13 ! videoconvert ! video/x-raw,width=640,height=480,format=BGR ! videoconvert ! appsink"
```

**Arguments:**

| Position | Value | Description |
|---|---|---|
| 1 | `/usr/local/lib/dx-models/YoloV8N.dxnn` | Path to the compiled `.dxnn` model file |
| 2 | `5` | Profile index — selects the post-processing configuration matching the model architecture and input size (see table below) |
| 3…N | GStreamer pipeline strings | One pipeline per camera; add or remove strings for more/fewer streams |

**Profile index mapping:**

| Index | Profile |
|---|---|
| 0 | yolov5s_320 |
| 1 | yolov5s_512 |
| 2 | yolov5s_640 |
| 3 | yolov7_512 |
| 4 | yolov7_640 |
| 5 | yolov8_640 |
| 6 | yolox_s_512 |
| 7 | yolov5s_face_640 |
| 8 | yolov3_512 |
| 9 | yolov4_416 |
| 10 | yolov9_640 |

The default value `5` corresponds to `yolov8_640`, matching the bundled `YoloV8N.dxnn` model. Change this index when using a different model architecture.

Each pipeline string must end with `appsink` — the application pulls frames from this element for inference. Changing the sink to anything else (e.g. `autovideosink`) will break the integration.

**Adapting the pipeline:**

- **Change camera device** — replace `device=/dev/video4` with the correct `/dev/videoX` node for your hardware.
- **Change resolution** — update `width=640,height=480` in both the `video/x-raw` caps and ensure your camera supports the chosen resolution at the chosen framerate.
- **Add a framerate cap** — append `,framerate=30/1` to the caps filter, e.g. `video/x-raw,width=640,height=480,framerate=30/1,format=BGR`.
- **Use a test source instead of a camera** — replace the `v4l2src` element with `videotestsrc pattern=ball` for offline testing without physical hardware.
- **Add a second camera** — append a second pipeline string as an additional argument; the app renders each stream in its own panel.

After editing the service file, apply the change with:

```sh
systemctl daemon-reload
systemctl restart qt-deepx-example
```
