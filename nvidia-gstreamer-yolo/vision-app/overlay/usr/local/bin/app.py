#!/usr/bin/env python3

import sys

import collections
import logging
import os
import time
import threading

import cv2
import numpy as np

import tensorrt as trt
try:
    from cuda import cudart
except ImportError:  # cuda-python >= 12.x relocated the runtime bindings
    from cuda.bindings import runtime as cudart

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from flask import Flask, Response, jsonify

# Engine builder lives next to this script; used to compute the engine path
# and to build it on demand if the oneshot service hasn't run yet.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_engine as engine_builder

app = Flask(__name__)

DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
FRAMERATE = int(os.environ.get("CAMERA_FRAMERATE", "30"))
PORT = int(os.environ.get("PORT", "5000"))
MODEL_PATH = os.environ.get("MODEL_PATH", "/usr/lib/app/models/yolo11n.onnx")
ENGINE_DIR = os.environ.get("ENGINE_DIR", "/var/lib/app")
INPUT_SIZE = int(os.environ.get("INPUT_SIZE", "640"))
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
    """Runs YOLO11 inference on the Jetson GPU via TensorRT.

    The ONNX is compiled to a TensorRT engine on-device (see build_engine.py);
    here we deserialize that engine, allocate CUDA buffers once, and run each
    frame through execute_async_v3. Pre/post-processing stays in OpenCV/NumPy on
    the CPU. If TensorRT can't initialize, we fall back to OpenCV-DNN on the CPU
    so the dashboard still works (clearly labeled as such).
    """

    def __init__(self, model_path):
        self.ready = False
        self._backend_name = "none"
        self._target_name = "none"
        self._cuda_device = None
        self._model_path = model_path
        self._engine_path = None
        self._fps = 0.0
        self._inference_times = collections.deque(maxlen=100)
        self._total_inferences = 0
        self._total_detections = 0

        # TensorRT state
        self._runtime = None
        self._engine = None
        self._context = None
        self._stream = None
        self._input_name = None
        self._output_name = None
        self._input_shape = None
        self._output_shape = None
        self._d_input = None
        self._d_output = None
        self._h_output = None
        self._input_nbytes = 0
        self._output_nbytes = 0

        # OpenCV-DNN CPU fallback
        self._net = None

        if not os.path.exists(model_path):
            log_det.error("model not found at %s", model_path)
            return

        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        log_det.info("model: %s (%.1f MB)", model_path, model_size_mb)

        if self._init_tensorrt(model_path):
            self.ready = True
        elif self._init_cpu_fallback(model_path):
            self.ready = True

        if self.ready:
            log_det.info("detector ready — backend=%s target=%s", self._backend_name, self._target_name)
        else:
            log_det.error("detector could not be initialized on GPU or CPU")

    # -- CUDA helper --------------------------------------------------------

    @staticmethod
    def _cuda_check(ret):
        """Unwrap a cuda-python return tuple (err, *out), raising on error."""
        if isinstance(ret, (tuple, list)):
            err, out = ret[0], ret[1:]
        else:
            err, out = ret, ()
        if err != cudart.cudaError_t.cudaSuccess:
            raise RuntimeError(f"CUDA error: {err}")
        if len(out) == 1:
            return out[0]
        return out or None

    def _query_cuda_device(self):
        try:
            return self._cuda_check(cudart.cudaGetDevice())
        except Exception:
            return None

    # -- TensorRT init ------------------------------------------------------

    def _load_engine(self, path):
        """Deserialize a TensorRT engine file. Returns None on failure (e.g. a
        prebuilt engine built against a different TensorRT version)."""
        try:
            log_det.info("loading TensorRT engine: %s", path)
            with open(path, "rb") as f:
                engine = self._runtime.deserialize_cuda_engine(f.read())
            if engine is None:
                log_det.warning("deserialize returned None for %s", path)
            return engine
        except Exception as e:
            log_det.warning("could not load engine %s: %s", path, e)
            return None

    def _init_tensorrt(self, model_path):
        try:
            logger = trt.Logger(trt.Logger.WARNING)
            trt.init_libnvinfer_plugins(logger, "")
            self._runtime = trt.Runtime(logger)

            # Engine acquisition order:
            #   1. on-device cache in /var (built or rebuilt here previously)
            #   2. prebuilt engine shipped read-only in the image (/usr) — the
            #      common case for users of this reference: zero build wait
            #   3. build on-device now (no prebuilt, or a model swap)
            cached = engine_builder.engine_path_for(model_path, ENGINE_DIR)
            prebuilt = engine_builder.prebuilt_engine_for(model_path)
            self._engine = None
            for cand in (cached, prebuilt):
                if cand and os.path.exists(cand):
                    self._engine = self._load_engine(cand)
                    if self._engine is not None:
                        self._engine_path = cand
                        break

            # Nothing loaded — either no engine was present, or a shipped
            # prebuilt failed to deserialize (a TensorRT version bump in the
            # feed invalidates an embedded engine). Build a fresh one on-device;
            # this is the self-healing path that keeps the reference working
            # across TRT upgrades and model swaps.
            if self._engine is None:
                self._engine_path = engine_builder.build_engine(model_path, ENGINE_DIR, force=True)
                self._engine = self._load_engine(self._engine_path)
            if self._engine is None:
                raise RuntimeError("failed to load or build a TensorRT engine")

            self._context = self._engine.create_execution_context()

            # Resolve the I/O tensors via the TRT 10 name-based API.
            for i in range(self._engine.num_io_tensors):
                name = self._engine.get_tensor_name(i)
                shape = tuple(self._engine.get_tensor_shape(name))
                if self._engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                    self._input_name, self._input_shape = name, shape
                else:
                    self._output_name, self._output_shape = name, shape

            if not self._input_name or not self._output_name:
                raise RuntimeError("could not resolve engine I/O tensors")

            # Allocate device + host buffers once (static shapes, FP32 I/O).
            self._input_nbytes = int(np.prod(self._input_shape)) * np.float32().itemsize
            self._output_nbytes = int(np.prod(self._output_shape)) * np.float32().itemsize
            self._d_input = self._cuda_check(cudart.cudaMalloc(self._input_nbytes))
            self._d_output = self._cuda_check(cudart.cudaMalloc(self._output_nbytes))
            self._h_output = np.empty(self._output_shape, dtype=np.float32)
            self._context.set_tensor_address(self._input_name, int(self._d_input))
            self._context.set_tensor_address(self._output_name, int(self._d_output))
            self._stream = self._cuda_check(cudart.cudaStreamCreate())

            # Warm up so the first real frame isn't penalized.
            t0 = time.monotonic()
            self._infer_trt(np.zeros(self._input_shape, dtype=np.float32))
            warmup_ms = (time.monotonic() - t0) * 1000

            self._backend_name = "TensorRT"
            self._target_name = "CUDA"
            self._cuda_device = self._query_cuda_device()
            log_det.info(
                "TensorRT engine active (warmup: %.0fms, in=%s out=%s)",
                warmup_ms, self._input_shape, self._output_shape,
            )
            return True
        except Exception as e:
            log_det.warning("TensorRT init failed: %s", e)
            self._teardown_trt()
            return False

    def _init_cpu_fallback(self, model_path):
        try:
            log_det.warning("falling back to CPU inference via OpenCV DNN (NO GPU acceleration)")
            self._net = cv2.dnn.readNetFromONNX(model_path)
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            self._backend_name = "OpenCV"
            self._target_name = "CPU"
            return True
        except Exception as e:
            log_det.error("CPU fallback failed: %s", e)
            return False

    def _teardown_trt(self):
        for ptr in (self._d_input, self._d_output):
            if ptr is not None:
                try:
                    cudart.cudaFree(ptr)
                except Exception:
                    pass
        if self._stream is not None:
            try:
                cudart.cudaStreamDestroy(self._stream)
            except Exception:
                pass
        self._engine = self._context = self._stream = None
        self._d_input = self._d_output = None

    # -- Inference ----------------------------------------------------------

    def _infer_trt(self, blob):
        """Run one TensorRT forward pass. blob: float32 NCHW matching input shape."""
        blob = np.ascontiguousarray(blob, dtype=np.float32)
        self._cuda_check(cudart.cudaMemcpyAsync(
            int(self._d_input), blob.ctypes.data, self._input_nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyHostToDevice, self._stream))
        self._context.execute_async_v3(self._stream)
        self._cuda_check(cudart.cudaMemcpyAsync(
            self._h_output.ctypes.data, int(self._d_output), self._output_nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, self._stream))
        self._cuda_check(cudart.cudaStreamSynchronize(self._stream))
        return self._h_output

    def detect(self, frame):
        if not self.ready:
            return frame, []

        h, w = frame.shape[:2]
        t0 = time.monotonic()

        # Preprocess: resize to the network's square input, scale to [0,1], BGR->RGB.
        blob = cv2.dnn.blobFromImage(
            frame, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False
        )

        if self._engine is not None:
            output = self._infer_trt(blob)
        else:
            self._net.setInput(blob)
            output = self._net.forward()

        # YOLO11 output shape: (1, 84, 8400) -> (8400, 84).
        preds = output[0].T

        x_scale = w / float(INPUT_SIZE)
        y_scale = h / float(INPUT_SIZE)

        # Vectorized confidence filter — avoids a Python loop over all 8400
        # candidates, which would otherwise become the bottleneck once GPU
        # inference is fast.
        class_scores = preds[:, 4:]
        class_ids_all = np.argmax(class_scores, axis=1)
        confidences_all = class_scores[np.arange(class_scores.shape[0]), class_ids_all]
        keep = confidences_all >= CONFIDENCE_THRESHOLD
        preds = preds[keep]
        class_ids_all = class_ids_all[keep]
        confidences_all = confidences_all[keep]

        boxes = []
        confidences = []
        class_ids = []
        for det, cid, conf in zip(preds, class_ids_all, confidences_all):
            cx, cy, bw, bh = det[:4]
            x1 = int((cx - bw / 2) * x_scale)
            y1 = int((cy - bh / 2) * y_scale)
            boxes.append([x1, y1, int(bw * x_scale), int(bh * y_scale)])
            confidences.append(float(conf))
            class_ids.append(int(cid))

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
            "engine": self._engine_path,
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
    log.info("tensorrt: %s", trt.__version__)
    log.info("confidence: %.2f  nms: %.2f", CONFIDENCE_THRESHOLD, NMS_THRESHOLD)
    log.info("log level: %s", LOG_LEVEL)
    log.info("dashboard: http://0.0.0.0:%d", PORT)

    # Prime CPU stats
    read_cpu()

    # Start camera
    camera.start()

    app.run(host="0.0.0.0", port=PORT)
