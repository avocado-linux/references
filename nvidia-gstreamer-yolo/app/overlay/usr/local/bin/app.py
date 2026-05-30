#!/usr/bin/env python3

import sys
sys.path.insert(0, "/usr/lib/app/packages")

import collections
import logging
import os
import time
import threading

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from flask import Flask, Response, jsonify

app = Flask(__name__)

DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
FRAMERATE = int(os.environ.get("CAMERA_FRAMERATE", "30"))
PORT = int(os.environ.get("PORT", "5000"))
MODEL_PATH = os.environ.get("MODEL_PATH", "/usr/lib/app/models/yolo11n.onnx")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))
NMS_THRESHOLD = float(os.environ.get("NMS_THRESHOLD", "0.45"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEVICE_ID = os.uname().nodename

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
for handler in logging.root.handlers:
    handler.flush = sys.stdout.flush

log = logging.getLogger("app")
log_det = logging.getLogger("detector")
log_cam = logging.getLogger("camera")
log_gst = logging.getLogger("gstreamer")

logging.getLogger("werkzeug").setLevel(
    logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.WARNING
)

# COCO class names for YOLO11
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

PIPELINE_NAMES = [
    "nvidia-mjpeg-decode",
    "nvidia-raw-capture",
    "software-mjpeg-decode",
    "software-raw-capture",
]


# ---------------------------------------------------------------------------
# YOLO detector
# ---------------------------------------------------------------------------

class YoloDetector:
    def __init__(self, model_path):
        self.net = None
        self.ready = False
        self._backend_name = "none"
        self._target_name = "none"
        self._cuda_device = None
        self._model_path = model_path
        self._fps = 0.0
        self._inference_times = collections.deque(maxlen=100)
        self._total_inferences = 0
        self._total_detections = 0

        if not os.path.exists(model_path):
            log_det.error("model not found at %s", model_path)
            return

        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        log_det.info("loading model: %s (%.1f MB)", model_path, model_size_mb)
        self.net = cv2.dnn.readNetFromONNX(model_path)

        # Try CUDA backend, fall back to CPU
        try:
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            # Run a dummy inference to confirm CUDA actually works
            log_det.info("testing CUDA backend with dummy inference...")
            dummy = np.zeros((1, 3, 640, 640), dtype=np.float32)
            self.net.setInput(dummy)
            t0 = time.monotonic()
            self.net.forward()
            warmup_ms = (time.monotonic() - t0) * 1000
            self._backend_name = "CUDA"
            self._target_name = "CUDA"
            log_det.info("CUDA backend active (warmup: %.0fms)", warmup_ms)
            self._log_cuda_info()
        except Exception as e:
            log_det.warning("CUDA unavailable: %s", e)
            log_det.info("falling back to CPU backend (OpenCV DNN)")
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            self._backend_name = "OpenCV"
            self._target_name = "CPU"
            # Log a CPU warmup too for comparison
            dummy = np.zeros((1, 3, 640, 640), dtype=np.float32)
            self.net.setInput(dummy)
            t0 = time.monotonic()
            self.net.forward()
            warmup_ms = (time.monotonic() - t0) * 1000
            log_det.info("CPU backend active (warmup: %.0fms)", warmup_ms)

        self.ready = True
        log_det.info("model loaded successfully — backend=%s target=%s", self._backend_name, self._target_name)

    def _log_cuda_info(self):
        """Log available CUDA device information from OpenCV."""
        try:
            cuda_count = cv2.cuda.getCudaEnabledDeviceCount()
            log_det.info("CUDA devices found: %d", cuda_count)
            for i in range(cuda_count):
                cv2.cuda.setDevice(i)
                dev = cv2.cuda.getDevice()
                log_det.info("  device %d: id=%d", i, dev)
                # Try to print device props if available
                try:
                    cv2.cuda.printCudaDeviceInfo(i)
                except Exception:
                    pass
            self._cuda_device = cv2.cuda.getDevice()
        except Exception as e:
            log_det.debug("could not query CUDA device info: %s", e)

    def detect(self, frame):
        if not self.ready:
            return frame, []

        h, w = frame.shape[:2]
        t0 = time.monotonic()

        # Preprocess: letterbox resize to 640x640
        blob = cv2.dnn.blobFromImage(
            frame, 1 / 255.0, (640, 640), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        outputs = self.net.forward()

        # YOLO11 output shape: (1, 84, 8400) -> transpose to (8400, 84)
        outputs = outputs[0].T

        boxes = []
        confidences = []
        class_ids = []

        x_scale = w / 640.0
        y_scale = h / 640.0

        for detection in outputs:
            scores = detection[4:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]

            if confidence < CONFIDENCE_THRESHOLD:
                continue

            cx, cy, bw, bh = detection[:4]
            x1 = int((cx - bw / 2) * x_scale)
            y1 = int((cy - bh / 2) * y_scale)
            bw_scaled = int(bw * x_scale)
            bh_scaled = int(bh * y_scale)

            boxes.append([x1, y1, bw_scaled, bh_scaled])
            confidences.append(float(confidence))
            class_ids.append(int(class_id))

        # Non-maximum suppression
        indices = cv2.dnn.NMSBoxes(boxes, confidences, CONFIDENCE_THRESHOLD, NMS_THRESHOLD) if boxes else []

        detections = []
        for i in indices:
            idx = int(i)
            x, y, bw, bh = boxes[idx]
            label = COCO_CLASSES[class_ids[idx]] if class_ids[idx] < len(COCO_CLASSES) else "unknown"
            conf = confidences[idx]
            detections.append({"label": label, "confidence": round(conf, 2), "box": [x, y, bw, bh]})

            # Draw bounding box
            color = (0, 255, 0)
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            text = f"{label} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x, y - th - 6), (x + tw, y), color, -1)
            cv2.putText(frame, text, (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        elapsed = time.monotonic() - t0
        self._fps = 1.0 / elapsed if elapsed > 0 else 0
        self._inference_times.append(elapsed * 1000)  # store in ms
        self._total_inferences += 1
        self._total_detections += len(detections)
        return frame, detections

    @property
    def fps(self):
        return round(self._fps, 1)

    @property
    def backend(self):
        return self._backend_name

    @property
    def target(self):
        return self._target_name

    @property
    def avg_inference_ms(self):
        if not self._inference_times:
            return 0.0
        return round(sum(self._inference_times) / len(self._inference_times), 1)

    @property
    def p95_inference_ms(self):
        if not self._inference_times:
            return 0.0
        sorted_times = sorted(self._inference_times)
        idx = int(len(sorted_times) * 0.95)
        return round(sorted_times[min(idx, len(sorted_times) - 1)], 1)

    @property
    def total_inferences(self):
        return self._total_inferences

    @property
    def total_detections(self):
        return self._total_detections

    def stats(self):
        return {
            "path": self._model_path,
            "loaded": self.ready,
            "backend": self._backend_name,
            "target": self._target_name,
            "cuda_device": self._cuda_device,
            "inference_fps": self.fps,
            "avg_inference_ms": self.avg_inference_ms,
            "p95_inference_ms": self.p95_inference_ms,
            "total_inferences": self._total_inferences,
            "total_detections": self._total_detections,
        }


detector = YoloDetector(MODEL_PATH)


# ---------------------------------------------------------------------------
# GStreamer camera capture
# ---------------------------------------------------------------------------

class Camera:
    def __init__(self):
        Gst.init(None)
        self._raw_frame = None
        self._lock = threading.Lock()
        self._pipeline = None
        self._running = False
        self._active_pipeline_name = None
        self._active_pipeline_str = None
        self._frame_count = 0
        self._start_time = None
        self._last_frame_time = None
        self._bus_errors = []
        self._bus_warnings = []
        self._bus_lock = threading.Lock()

    # -- GStreamer bus message handler --------------------------------------

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "error": str(err),
                "debug": debug or "",
            }
            log_gst.error("pipeline error: %s (debug: %s)", err, debug)
            with self._bus_lock:
                self._bus_errors.append(entry)
                self._bus_errors = self._bus_errors[-20:]
        elif t == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "warning": str(warn),
                "debug": debug or "",
            }
            log_gst.warning("pipeline warning: %s (debug: %s)", warn, debug)
            with self._bus_lock:
                self._bus_warnings.append(entry)
                self._bus_warnings = self._bus_warnings[-20:]
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self._pipeline:
                old, new, pending = message.parse_state_changed()
                log_gst.debug(
                    "pipeline state: %s -> %s (pending: %s)",
                    old.value_nick, new.value_nick, pending.value_nick,
                )
        elif t == Gst.MessageType.EOS:
            log_gst.warning("end-of-stream received")
        return True

    # -- Pipeline lifecycle -------------------------------------------------

    def start(self):
        # Pipelines ordered to prefer GPU-accelerated paths on Jetson.
        # nvvidconv handles color conversion on GPU instead of CPU videoconvert.
        pipelines = [
            # 1. MJPEG from camera -> NVIDIA hardware decode + convert to BGR
            (
                f"v4l2src device={DEVICE} "
                f"! image/jpeg,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
                f"! nvjpegdec "
                f"! video/x-raw(memory:NVMM) "
                f"! nvvidconv "
                f"! video/x-raw "
                f"! videoconvert "
                f"! video/x-raw,format=BGR "
                f"! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
            ),
            # 2. Raw video from camera -> NVIDIA hardware convert to BGR
            (
                f"v4l2src device={DEVICE} "
                f"! video/x-raw,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
                f"! nvvidconv "
                f"! video/x-raw "
                f"! videoconvert "
                f"! video/x-raw,format=BGR "
                f"! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
            ),
            # 3. MJPEG from camera -> CPU software decode + convert to BGR
            (
                f"v4l2src device={DEVICE} "
                f"! image/jpeg,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
                f"! jpegdec "
                f"! videoconvert "
                f"! video/x-raw,format=BGR "
                f"! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
            ),
            # 4. Raw video from camera -> CPU software convert to BGR
            (
                f"v4l2src device={DEVICE} "
                f"! video/x-raw,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 "
                f"! videoconvert "
                f"! video/x-raw,format=BGR "
                f"! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2"
            ),
        ]

        for i, pipeline_str in enumerate(pipelines):
            name = PIPELINE_NAMES[i]
            log_cam.info("trying pipeline %d/%d [%s]...", i + 1, len(pipelines), name)
            log_cam.debug("pipeline string: %s", pipeline_str)
            try:
                self._pipeline = Gst.parse_launch(pipeline_str)

                bus = self._pipeline.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self._on_bus_message)

                sink = self._pipeline.get_by_name("sink")
                sink.set_property("caps", Gst.Caps.from_string("video/x-raw,format=BGR"))
                sink.connect("new-sample", self._on_new_sample)

                ret = self._pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    log_cam.warning("[%s] failed to set PLAYING state", name)
                    self._pipeline.set_state(Gst.State.NULL)
                    continue

                ret = self._pipeline.get_state(2 * Gst.SECOND)
                if ret[0] == Gst.StateChangeReturn.FAILURE:
                    log_cam.warning("[%s] pipeline failed during state transition", name)
                    self._pipeline.set_state(Gst.State.NULL)
                    continue

                self._running = True
                self._active_pipeline_name = name
                self._active_pipeline_str = pipeline_str
                self._start_time = time.monotonic()

                is_gpu = name.startswith("nvidia-")
                log_cam.info("pipeline started: [%s] (GPU=%s)", name, is_gpu)
                if is_gpu:
                    log_cam.info("GPU-accelerated video capture active via nvvidconv")
                else:
                    log_cam.info("using CPU software video capture")

                self._loop = GLib.MainLoop()
                self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
                self._loop_thread.start()

                # Start periodic stats logger
                self._stats_thread = threading.Thread(target=self._log_periodic_stats, daemon=True)
                self._stats_thread.start()
                return

            except GLib.Error as e:
                log_cam.warning("[%s] GLib error: %s", name, e)
                if self._pipeline:
                    self._pipeline.set_state(Gst.State.NULL)
                continue

        log_cam.error("no camera pipeline could be started")
        log_cam.error("the dashboard will still work but /stream will be unavailable")

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample:
            buf = sample.get_buffer()
            caps = sample.get_caps()
            w = caps.get_structure(0).get_value("width")
            h = caps.get_structure(0).get_value("height")
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if ok:
                frame = np.frombuffer(mapinfo.data, dtype=np.uint8).reshape((h, w, 3))
                with self._lock:
                    self._raw_frame = frame.copy()
                    self._frame_count += 1
                    self._last_frame_time = time.monotonic()
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def get_frame(self):
        with self._lock:
            return self._raw_frame.copy() if self._raw_frame is not None else None

    @property
    def running(self):
        return self._running

    @property
    def pipeline_name(self):
        return self._active_pipeline_name

    @property
    def pipeline_str(self):
        return self._active_pipeline_str

    @property
    def uses_gpu(self):
        return self._active_pipeline_name is not None and self._active_pipeline_name.startswith("nvidia-")

    @property
    def fps(self):
        if not self._start_time or not self._frame_count:
            return 0.0
        elapsed = time.monotonic() - self._start_time
        return round(self._frame_count / elapsed, 1) if elapsed > 0 else 0.0

    @property
    def frame_count(self):
        return self._frame_count

    @property
    def uptime_seconds(self):
        if not self._start_time:
            return 0
        return int(time.monotonic() - self._start_time)

    @property
    def seconds_since_last_frame(self):
        if self._last_frame_time is None:
            return None
        return round(time.monotonic() - self._last_frame_time, 1)

    def bus_errors(self):
        with self._bus_lock:
            return list(self._bus_errors)

    def bus_warnings(self):
        with self._bus_lock:
            return list(self._bus_warnings)

    def _log_periodic_stats(self):
        while self._running:
            time.sleep(30)
            if not self._running:
                break
            stale = self.seconds_since_last_frame
            stale_str = f"{stale}s ago" if stale is not None else "never"
            log_cam.info(
                "camera stats: pipeline=%s gpu=%s frames=%d avg_fps=%.1f last_frame=%s",
                self._active_pipeline_name, self.uses_gpu,
                self._frame_count, self.fps, stale_str,
            )
            log_det.info(
                "detector stats: backend=%s target=%s inferences=%d avg=%.1fms p95=%.1fms fps=%.1f detections=%d",
                detector.backend, detector.target,
                detector.total_inferences, detector.avg_inference_ms,
                detector.p95_inference_ms, detector.fps,
                detector.total_detections,
            )
            with self._bus_lock:
                err_count = len(self._bus_errors)
                warn_count = len(self._bus_warnings)
            if err_count or warn_count:
                log_gst.info("bus messages: errors=%d warnings=%d", err_count, warn_count)


camera = Camera()


# ---------------------------------------------------------------------------
# Annotated frame generator
# ---------------------------------------------------------------------------

_latest_detections = []
_detections_lock = threading.Lock()


def generate_mjpeg():
    global _latest_detections
    while True:
        frame = camera.get_frame()
        if frame is not None:
            annotated, detections = detector.detect(frame)
            with _detections_lock:
                _latest_detections = detections
            _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            data = jpeg.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                + data + b"\r\n"
            )
        else:
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

_prev_cpu = None


def read_cpu():
    global _prev_cpu
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = list(map(int, parts[1:9]))
        total = sum(vals)
        idle = vals[3] + vals[4]
        percent = 0.0
        if _prev_cpu:
            dt = total - _prev_cpu[0]
            di = idle - _prev_cpu[1]
            percent = round((1 - di / dt) * 100, 1) if dt else 0.0
        _prev_cpu = (total, idle)
        return {"percent": percent}
    except Exception as e:
        log.debug("failed to read CPU stats: %s", e)
        return {"percent": 0.0}


def read_memory():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key = line.split(":")[0]
                if key in ("MemTotal", "MemFree", "MemAvailable"):
                    info[key] = int(line.split()[1])
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        used = total - available
        return {
            "total_mb": total // 1024,
            "used_mb": used // 1024,
            "percent": round(used / total * 100, 1) if total else 0,
        }
    except Exception as e:
        log.debug("failed to read memory stats: %s", e)
        return {"total_mb": 0, "used_mb": 0, "percent": 0}


def read_temperature():
    try:
        for zone in sorted(os.listdir("/sys/class/thermal")):
            p = f"/sys/class/thermal/{zone}/temp"
            if os.path.exists(p):
                with open(p) as f:
                    c = int(f.read().strip()) / 1000.0
                    return {"celsius": round(c, 1)}
    except (OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    with _detections_lock:
        det = list(_latest_detections)
    return jsonify({
        "timestamp": int(time.time()),
        "hostname": DEVICE_ID,
        "kernel": os.uname().release,
        "cpu": read_cpu(),
        "memory": read_memory(),
        "temperature": read_temperature(),
        "camera": {
            "device": DEVICE,
            "running": camera.running,
            "pipeline": camera.pipeline_name,
            "pipeline_detail": camera.pipeline_str,
            "uses_gpu": camera.uses_gpu,
            "resolution": f"{WIDTH}x{HEIGHT}@{FRAMERATE}fps",
            "fps": camera.fps,
            "frame_count": camera.frame_count,
            "uptime_seconds": camera.uptime_seconds,
            "last_frame_ago": camera.seconds_since_last_frame,
        },
        "model": detector.stats(),
        "detections": det,
        "gstreamer": {
            "errors": camera.bus_errors(),
            "warnings": camera.bus_warnings(),
        },
    })


@app.route("/api/detections")
def api_detections():
    with _detections_lock:
        det = list(_latest_detections)
    return jsonify(det)


@app.route("/stream")
def stream():
    if not camera.running:
        return "No camera available", 503
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avocado YOLO Camera Dashboard</title>
<style>
  :root {
    --bg: #09090b; --surface: #18181b; --border: #27272a; --text: #fafafa;
    --muted: #a1a1aa; --green: #84cc16; --green-dim: #3f6212;
    --blue: #38bdf8; --red: #f87171; --amber: #fbbf24; --amber-dim: #78350f;
    --purple: #a78bfa; --purple-dim: #4c1d95;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: ui-monospace, "SF Mono", Menlo, monospace; background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }

  header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
  header h1 { font-size: 20px; font-weight: 600; }
  header h1 span { color: var(--green); }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 9999px; font-weight: 500; }
  .badge-green { background: var(--green-dim); color: var(--green); }
  .badge-blue { background: #1e3a5f; color: var(--blue); }
  .badge-amber { background: var(--amber-dim); color: var(--amber); }
  .badge-red { background: #7f1d1d; color: var(--red); }
  .badge-purple { background: var(--purple-dim); color: var(--purple); }
  .meta { margin-left: auto; font-size: 12px; color: var(--muted); text-align: right; }

  .grid { display: grid; gap: 16px; margin-bottom: 16px; }
  .grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 12px; }
  .card-value { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
  .card-sub { font-size: 12px; color: var(--muted); }

  .bar-track { width: 100%; height: 8px; background: var(--border); border-radius: 4px; margin: 10px 0; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.6s ease; }

  .video-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 16px; }
  .video-card .card-title { padding: 20px 20px 12px; }
  .video-card img { width: 100%; display: block; background: #000; }
  .video-card .no-camera { padding: 60px 20px; text-align: center; color: var(--muted); background: #000; }

  .detail-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .detail-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 4px; }
  .detail-value { font-size: 13px; color: var(--text); margin-bottom: 12px; word-break: break-all; }
  .detail-value code { background: var(--bg); padding: 2px 6px; border-radius: 4px; font-size: 12px; }

  .det-list { margin-top: 8px; }
  .det-item { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .det-item:last-child { border-bottom: none; }
  .det-label { font-weight: 600; min-width: 120px; }
  .det-conf { color: var(--green); min-width: 50px; }

  .log-section { margin-top: 16px; }
  .log-section h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 8px; }
  .log-entry { font-size: 12px; padding: 6px 10px; border-left: 3px solid var(--border); margin-bottom: 4px; background: var(--bg); border-radius: 0 4px 4px 0; }
  .log-entry.error { border-left-color: var(--red); }
  .log-entry.warning { border-left-color: var(--amber); }
  .log-time { color: var(--muted); margin-right: 8px; }
  .log-empty { font-size: 12px; color: var(--muted); padding: 6px 10px; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1><span>avocado</span> yolo camera</h1>
    <span class="badge badge-green" id="live-badge">connecting</span>
    <span class="badge" id="pipeline-badge" style="display:none"></span>
    <span class="badge" id="backend-badge" style="display:none"></span>
    <div class="meta">
      <div id="hostname"></div>
      <div id="model-info"></div>
    </div>
  </header>

  <div class="video-card">
    <div class="card-title">Live Detection Feed</div>
    <div id="video-container">
      <div class="no-camera" id="no-camera">checking camera...</div>
    </div>
  </div>

  <div class="grid grid-4" id="stats-cards"></div>

  <div class="card" id="detections-card">
    <div class="card-title">Detected Objects</div>
    <div class="det-list" id="det-list">
      <div style="color:var(--muted);font-size:13px;padding:8px 12px">waiting for detections...</div>
    </div>
  </div>

  <div class="detail-card">
    <div class="card-title">Pipeline & Model Status</div>
    <div class="detail-grid" id="detail-grid"></div>
    <div class="log-section" id="gst-logs"></div>
  </div>
</div>

<script>
(function() {
  var POLL_MS = 1000;

  function card(title, value, sub, barPct, barColor) {
    var html = '<div class="card"><div class="card-title">' + title + '</div>' +
      '<div class="card-value">' + value + '</div>' +
      '<div class="card-sub">' + sub + '</div>';
    if (barPct !== undefined) {
      html += '<div class="bar-track"><div class="bar-fill" style="width:' + barPct +
        '%;background:' + (barColor || 'var(--green)') + '"></div></div>';
    }
    return html + '</div>';
  }

  function detail(label, value) {
    return '<div><div class="detail-label">' + label + '</div><div class="detail-value">' + value + '</div></div>';
  }

  function formatSeconds(s) {
    if (s === null || s === undefined) return "n/a";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    var parts = [];
    if (d) parts.push(d + "d");
    if (h) parts.push(h + "h");
    parts.push(m + "m");
    return parts.join(" ");
  }

  function renderStats(s) {
    document.getElementById("hostname").textContent = s.hostname;
    document.getElementById("model-info").textContent = s.model.loaded
      ? "YOLO11n on " + s.model.backend + "/" + s.model.target
      : "model not loaded";

    // Live badge
    var badge = document.getElementById("live-badge");
    badge.textContent = "live"; badge.className = "badge badge-green";

    // Pipeline badge
    var pb = document.getElementById("pipeline-badge");
    if (s.camera) {
      pb.style.display = "";
      var pName = (s.camera.pipeline || "none").replace(/-/g, " ");
      pb.textContent = pName;
      pb.className = "badge " + (s.camera.uses_gpu ? "badge-green" : "badge-amber");
    }

    // Backend badge
    var bb = document.getElementById("backend-badge");
    if (s.model) {
      bb.style.display = "";
      bb.textContent = s.model.backend + "/" + s.model.target;
      bb.className = "badge " + (s.model.target === "CUDA" ? "badge-purple" : "badge-amber");
    }

    // Video
    var container = document.getElementById("video-container");
    if (s.camera && s.camera.running) {
      if (!document.getElementById("camera-img")) {
        container.innerHTML = '<img id="camera-img" src="/stream" alt="Detection Feed">';
      }
    } else {
      if (!document.getElementById("camera-img")) {
        document.getElementById("no-camera").textContent = "no camera detected at " + (s.camera ? s.camera.device : "unknown");
      }
    }

    // Stats cards
    var html = "";
    html += card("Inference", s.model.inference_fps + " fps",
      s.model.avg_inference_ms + "ms avg / " + s.model.p95_inference_ms + "ms p95");
    html += card("CPU", s.cpu.percent + "%", "usage", s.cpu.percent, "var(--green)");
    html += card("Memory", s.memory.percent + "%",
      s.memory.used_mb + " / " + s.memory.total_mb + " MB", s.memory.percent, "var(--blue)");
    html += card("Camera FPS", (s.camera.fps || "0"),
      s.camera.frame_count + " total frames");
    if (s.temperature) {
      html += card("Temperature", s.temperature.celsius + " &deg;C", "GPU/SoC");
    }
    html += card("Detections", s.model.total_detections.toLocaleString(),
      s.model.total_inferences.toLocaleString() + " inferences");
    document.getElementById("stats-cards").innerHTML = html;

    // Detections list
    var dl = document.getElementById("det-list");
    if (s.detections && s.detections.length > 0) {
      dl.innerHTML = s.detections.map(function(d) {
        return '<div class="det-item">' +
          '<span class="det-label">' + d.label + '</span>' +
          '<span class="det-conf">' + (d.confidence * 100).toFixed(0) + '%</span></div>';
      }).join("");
    } else {
      dl.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 12px">no objects detected</div>';
    }

    // Detail grid
    var dg = "";
    // Camera details
    dg += detail("Camera Pipeline", '<code>' + (s.camera.pipeline || "none") + '</code>');
    dg += detail("Camera GPU", s.camera.uses_gpu
      ? '<span style="color:var(--green)">yes (nvvidconv)</span>'
      : '<span style="color:var(--amber)">no (CPU videoconvert)</span>');
    dg += detail("Resolution", s.camera.resolution);
    dg += detail("Pipeline Uptime", formatSeconds(s.camera.uptime_seconds));

    var lastFrame = s.camera.last_frame_ago;
    var lfStyle = "";
    if (lastFrame !== null && lastFrame > 2) lfStyle = ' style="color:var(--amber)"';
    if (lastFrame !== null && lastFrame > 10) lfStyle = ' style="color:var(--red)"';
    dg += detail("Last Frame", '<span' + lfStyle + '>' + (lastFrame !== null ? lastFrame + 's ago' : 'no frames yet') + '</span>');

    // Model details
    dg += detail("Model Backend", '<code>' + s.model.backend + '</code> target=<code>' + s.model.target + '</code>');
    dg += detail("CUDA Device", s.model.cuda_device !== null ? 'device ' + s.model.cuda_device : '<span style="color:var(--amber)">not available</span>');
    dg += detail("Inference Timing", s.model.avg_inference_ms + 'ms avg / ' + s.model.p95_inference_ms + 'ms p95');

    if (s.camera.pipeline_detail) {
      dg += '<div style="grid-column:1/-1"><div class="detail-label">Pipeline String</div><div class="detail-value" style="font-size:11px;color:var(--muted)">' + s.camera.pipeline_detail + '</div></div>';
    }
    document.getElementById("detail-grid").innerHTML = dg;

    // GStreamer logs
    var gl = "";
    var errors = (s.gstreamer && s.gstreamer.errors) || [];
    var warnings = (s.gstreamer && s.gstreamer.warnings) || [];
    if (errors.length > 0) {
      gl += '<h3>Errors (' + errors.length + ')</h3>';
      for (var i = errors.length - 1; i >= Math.max(0, errors.length - 5); i--) {
        gl += '<div class="log-entry error"><span class="log-time">' + errors[i].time + '</span>' + errors[i].error + '</div>';
      }
    }
    if (warnings.length > 0) {
      gl += '<h3>Warnings (' + warnings.length + ')</h3>';
      for (var i = warnings.length - 1; i >= Math.max(0, warnings.length - 5); i--) {
        gl += '<div class="log-entry warning"><span class="log-time">' + warnings[i].time + '</span>' + warnings[i].warning + '</div>';
      }
    }
    if (!errors.length && !warnings.length) {
      gl = '<div class="log-empty">no gstreamer issues</div>';
    }
    document.getElementById("gst-logs").innerHTML = gl;
  }

  async function poll() {
    try {
      var res = await fetch("/api/stats");
      if (!res.ok) throw new Error();
      renderStats(await res.json());
    } catch (e) {
      var badge = document.getElementById("live-badge");
      badge.textContent = "offline"; badge.className = "badge badge-red";
    }
    setTimeout(poll, POLL_MS);
  }

  poll();
})();
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, content_type="text/html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("app starting")
    log.info("device: %s", DEVICE_ID)
    log.info("camera: %s (%dx%d@%dfps)", DEVICE, WIDTH, HEIGHT, FRAMERATE)
    log.info("model: %s", MODEL_PATH)
    log.info("confidence: %.2f  nms: %.2f", CONFIDENCE_THRESHOLD, NMS_THRESHOLD)
    log.info("log level: %s", LOG_LEVEL)
    log.info("dashboard: http://0.0.0.0:%d", PORT)

    # OpenCV build info for debugging CUDA availability
    build_info = cv2.getBuildInformation()
    cuda_lines = [l.strip() for l in build_info.split("\n") if "CUDA" in l or "cuDNN" in l]
    if cuda_lines:
        log_det.info("OpenCV CUDA build info:")
        for line in cuda_lines:
            log_det.info("  %s", line)
    else:
        log_det.warning("no CUDA references found in OpenCV build info — CUDA likely not compiled in")

    # Prime CPU stats
    read_cpu()

    # Start camera
    camera.start()

    app.run(host="0.0.0.0", port=PORT)
