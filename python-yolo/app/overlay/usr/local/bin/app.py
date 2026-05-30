#!/usr/bin/env python3

import sys
sys.path.insert(0, "/usr/lib/app/packages")

import collections
import logging
import os
import threading
import time

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from flask import Flask, Response, jsonify

app = Flask(__name__)

DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
WIDTH = int(os.environ.get("CAMERA_WIDTH", "640"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "480"))
FRAMERATE = int(os.environ.get("CAMERA_FRAMERATE", "30"))
PORT = int(os.environ.get("PORT", "5000"))
MODEL_PATH = os.environ.get("MODEL_PATH", "/usr/lib/app/models/yolov8n-416.onnx")
INPUT_SIZE = int(os.environ.get("INPUT_SIZE", "416"))
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.35"))
NMS_THRESHOLD = float(os.environ.get("NMS_THRESHOLD", "0.45"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEVICE_ID = os.uname().nodename

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("app")
log_det = logging.getLogger("detector")
log_cam = logging.getLogger("camera")
logging.getLogger("werkzeug").setLevel(logging.WARNING)


COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


class YoloDetector:
    # YOLOv8 ONNX export is anchor-free: a single output of shape (1, 84, N).
    # Channels 0..3 are box (cx, cy, w, h) in pixel coords of the model input;
    # channels 4..83 are per-class probabilities (sigmoid already applied at
    # export). Preprocess is the standard "BGR -> RGB, /255, NCHW".
    def __init__(self, model_path, input_size):
        self.ready = False
        self.input_size = input_size
        self.model_path = model_path
        self._fps = 0.0
        self._inference_times = collections.deque(maxlen=100)
        self._total_inferences = 0
        self._total_detections = 0

        if not os.path.exists(model_path):
            log_det.error("model not found: %s", model_path)
            return

        log_det.info("loading model: %s", model_path)
        self.net = cv2.dnn.readNetFromONNX(model_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        t0 = time.monotonic()
        self.net.setInput(np.zeros((1, 3, input_size, input_size), dtype=np.float32))
        self.net.forward()
        log_det.info("warmup: %.0fms; backend=OpenCV target=CPU", (time.monotonic() - t0) * 1000)
        self.ready = True

    def detect(self, frame):
        if not self.ready:
            return frame, []

        h, w = frame.shape[:2]
        t0 = time.monotonic()

        blob = cv2.dnn.blobFromImage(
            frame, 1 / 255.0, (self.input_size, self.input_size), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        out = self.net.forward()  # (1, 84, N)
        preds = out[0].T          # (N, 84)

        scores_all = preds[:, 4:]
        class_ids = np.argmax(scores_all, axis=1)
        confidences = scores_all[np.arange(len(scores_all)), class_ids]

        keep = confidences >= CONFIDENCE_THRESHOLD
        if not keep.any():
            self._record(time.monotonic() - t0, 0)
            return frame, []

        boxes_xywh = preds[keep, :4]
        confidences = confidences[keep]
        class_ids = class_ids[keep]

        x_scale = w / self.input_size
        y_scale = h / self.input_size
        x1 = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) * x_scale
        y1 = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) * y_scale
        bw = boxes_xywh[:, 2] * x_scale
        bh = boxes_xywh[:, 3] * y_scale
        boxes = np.stack([x1, y1, bw, bh], axis=1).astype(np.int32)

        indices = cv2.dnn.NMSBoxes(
            boxes.tolist(), confidences.tolist(),
            CONFIDENCE_THRESHOLD, NMS_THRESHOLD,
        )

        detections = []
        for i in indices:
            idx = int(i)
            x, y, box_w, box_h = boxes[idx].tolist()
            cid = int(class_ids[idx])
            label = COCO_CLASSES[cid] if cid < len(COCO_CLASSES) else "?"
            conf = float(confidences[idx])
            detections.append({"label": label, "confidence": round(conf, 2), "box": [x, y, box_w, box_h]})

            color = (0, 255, 0)
            cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), color, 2)
            text = f"{label} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x, y - th - 6), (x + tw, y), color, -1)
            cv2.putText(frame, text, (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        people = sum(1 for d in detections if d["label"] == "person")
        cv2.putText(frame, f"objects: {len(detections)}  people: {people}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        self._record(time.monotonic() - t0, len(detections))
        return frame, detections

    def _record(self, elapsed_s, n):
        self._fps = 1.0 / elapsed_s if elapsed_s > 0 else 0.0
        self._inference_times.append(elapsed_s * 1000)
        self._total_inferences += 1
        self._total_detections += n

    @property
    def fps(self):
        return round(self._fps, 1)

    @property
    def avg_inference_ms(self):
        if not self._inference_times:
            return 0.0
        return round(sum(self._inference_times) / len(self._inference_times), 1)

    def stats(self):
        return {
            "path": self.model_path,
            "loaded": self.ready,
            "backend": "OpenCV",
            "target": "CPU",
            "input_size": self.input_size,
            "inference_fps": self.fps,
            "avg_inference_ms": self.avg_inference_ms,
            "total_inferences": self._total_inferences,
            "total_detections": self._total_detections,
        }


detector = YoloDetector(MODEL_PATH, INPUT_SIZE)


class Camera:
    PIPELINES = [
        ("mjpeg", lambda: (
            f"v4l2src device={DEVICE} ! "
            f"image/jpeg,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 ! "
            f"jpegdec ! videoconvert ! video/x-raw,format=BGR ! "
            f"appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
        )),
        ("raw", lambda: (
            f"v4l2src device={DEVICE} ! "
            f"video/x-raw,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            f"appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
        )),
    ]

    def __init__(self):
        Gst.init(None)
        self._frame = None
        self._lock = threading.Lock()
        self._pipeline = None
        self._loop = None
        self._loop_thread = None
        self._active = None
        self._frame_count = 0
        self._start_time = None
        self._last_frame_time = None

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps()
        w = caps.get_structure(0).get_value("width")
        h = caps.get_structure(0).get_value("height")
        success, info = buf.map(Gst.MapFlags.READ)
        if success:
            frame = np.frombuffer(info.data, dtype=np.uint8).reshape((h, w, 3)).copy()
            buf.unmap(info)
            with self._lock:
                self._frame = frame
                self._frame_count += 1
                self._last_frame_time = time.monotonic()
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, dbg = message.parse_error()
            log_cam.error("pipeline error: %s (%s)", err, dbg)

    def start(self):
        for name, build in self.PIPELINES:
            pipeline_str = build()
            log_cam.info("trying pipeline %s: %s", name, pipeline_str)
            try:
                pipeline = Gst.parse_launch(pipeline_str)
            except GLib.Error as e:
                log_cam.warning("parse failed: %s", e)
                continue
            sink = pipeline.get_by_name("sink")
            sink.connect("new-sample", self._on_new_sample)
            bus = pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)
            ret = pipeline.set_state(Gst.State.PLAYING)
            ret, *_ = pipeline.get_state(Gst.CLOCK_TIME_NONE)
            if ret == Gst.StateChangeReturn.FAILURE:
                log_cam.warning("pipeline %s failed to start", name)
                pipeline.set_state(Gst.State.NULL)
                continue
            self._pipeline = pipeline
            self._active = name
            self._start_time = time.monotonic()
            self._loop = GLib.MainLoop()
            self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
            self._loop_thread.start()
            log_cam.info("camera running via '%s'", name)
            return True
        log_cam.error("no pipeline could start")
        return False

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stats(self):
        with self._lock:
            uptime = (time.monotonic() - self._start_time) if self._start_time else 0
            last_ago = (time.monotonic() - self._last_frame_time) if self._last_frame_time else None
            fps = (self._frame_count / uptime) if uptime > 0 else 0.0
        return {
            "device": DEVICE,
            "pipeline": self._active or "none",
            "resolution": f"{WIDTH}x{HEIGHT}@{FRAMERATE}fps",
            "fps": round(fps, 1),
            "frame_count": self._frame_count,
            "last_frame_ago": round(last_ago, 1) if last_ago is not None else None,
            "uptime_seconds": int(uptime),
        }


camera = Camera()


_latest = []
_latest_lock = threading.Lock()


def generate_mjpeg():
    global _latest
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        annotated, detections = detector.detect(frame)
        with _latest_lock:
            _latest = detections
        _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = jpeg.tobytes()
        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
               + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")


@app.route("/")
def index():
    return f"""<!DOCTYPE html>
<html><head><title>Object Detection — {DEVICE_ID}</title>
<style>
body {{ background: #0a0a0b; color: #e5e5e7; font-family: ui-monospace, monospace; margin: 0; padding: 24px; }}
header {{ display: flex; gap: 8px; align-items: baseline; margin-bottom: 16px; flex-wrap: wrap; }}
h1 {{ font-size: 18px; font-weight: 600; margin-right: 8px; }}
.badge {{ padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 500; }}
.badge-green {{ background: #1f3a1f; color: #84cc16; }}
.badge-blue {{ background: #0e2a3f; color: #38bdf8; }}
.badge-amber {{ background: #3a2a0a; color: #fbbf24; }}
.badge-gray {{ background: #18181b; color: #a1a1aa; border: 1px solid #27272a; }}
img {{ max-width: 100%; border: 1px solid #27272a; border-radius: 8px; display: block; }}
.meta {{ font-size: 12px; color: #71717a; margin-top: 12px; }}
.meta a {{ color: #38bdf8; }}
</style></head>
<body>
<header>
  <h1>{DEVICE_ID}</h1>
  <span class="badge badge-green">object detection · CPU</span>
  <span class="badge badge-blue" id="b-cam">camera —</span>
  <span class="badge badge-amber" id="b-inf">inference —</span>
  <span class="badge badge-gray" id="b-lat">latency —</span>
  <span class="badge badge-gray" id="b-cnt">detections —</span>
</header>
<img src="/stream" />
<div class="meta">
  Live stream from /stream · JSON metrics at <a href="/api/stats">/api/stats</a>
</div>
<script>
async function tick() {{
  try {{
    const r = await fetch("/api/stats", {{ cache: "no-store" }});
    if (!r.ok) return;
    const d = await r.json();
    const cam = d.camera || {{}};
    const mdl = d.model  || {{}};
    document.getElementById("b-cam").textContent = `camera ${{(cam.fps ?? 0).toFixed(1)}} fps`;
    document.getElementById("b-inf").textContent = `inference ${{(mdl.inference_fps ?? 0).toFixed(1)}} fps`;
    document.getElementById("b-lat").textContent = `latency ${{(mdl.avg_inference_ms ?? 0).toFixed(0)}} ms`;
    document.getElementById("b-cnt").textContent = `detections ${{(d.detections || []).length}}`;
  }} catch (e) {{}}
}}
tick(); setInterval(tick, 1000);
</script>
</body></html>"""


@app.route("/stream")
def stream():
    return Response(generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/stats")
def api_stats():
    with _latest_lock:
        dets = list(_latest)
    return jsonify({
        "device": DEVICE_ID,
        "camera": camera.stats(),
        "model": detector.stats(),
        "detections": dets,
    })


def main():
    log.info("app starting on %s", DEVICE_ID)
    log.info("model: %s (input %dx%d)", MODEL_PATH, INPUT_SIZE, INPUT_SIZE)
    log.info("dashboard: http://0.0.0.0:%d", PORT)

    if not camera.start():
        log.error("camera failed to start; exiting")
        sys.exit(1)

    app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
