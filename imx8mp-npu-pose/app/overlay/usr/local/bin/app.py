#!/usr/bin/env python3
"""Live single-person pose estimation on the i.MX8M Plus NPU (MoveNet INT8).

One CNN forward pass per frame -> 17 COCO keypoints; we draw the skeleton over
the live video. The NPU runs the conv backbone (VX delegate); decoding + drawing
are CPU-side (cheap).

Pipeline (camera is cropped to a square so keypoint coords map 1:1 to pixels --
no letterbox math):

    v4l2src -> aspectratiocrop 1:1 -> tee --+--> cairooverlay(skeleton) --+--> waylandsink   (USE_DISPLAY)
                                            |                              +--> jpegenc -> appsink (WEB_PORT)
                                            +--> scale 192 -> tensor_converter
                                                 -> tensor_filter (MoveNet INT8, VX delegate)
                                                 -> tensor_sink   (Python decodes 17 keypoints)

USE_NPU=0 runs the same model on the CPU for comparison. Headless + WEB_PORT gives
a browser skeleton view with no display (open http://<board>:<port>/).

MultiPose later: swap the model + the decode in on_pose (MultiPose emits [1,6,56]).

Env: MODEL, LABELS(unused), CAMERA_DEVICE(auto), PREVIEW_SIZE(480), USE_NPU(1),
     USE_DISPLAY(auto), WEB_PORT(8080), SCORE_THRESH(0.3)
"""
import fcntl
import glob
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_foreign("cairo")
import cairo  # noqa: E402  (pycairo; used by the cairooverlay draw callback)
from gi.repository import GLib, Gst  # noqa: E402

APPDIR = "/usr/lib/imx8mp-npu-pose"
MODEL = os.environ.get("MODEL", f"{APPDIR}/movenet_int8.tflite")
VX_DELEGATE = "/usr/lib/libvx_delegate.so"
USE_NPU = os.environ.get("USE_NPU", "1") == "1"
PREVIEW = int(os.environ.get("PREVIEW_SIZE", "480"))
INPUT = 192
SCORE_THRESH = float(os.environ.get("SCORE_THRESH", "0.3"))

try:
    WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
except ValueError:
    WEB_PORT = 0

# COCO-17 skeleton (MoveNet keypoint order): edges to connect.
EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6),
    (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11),
    (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
]


def _pick_camera():
    """First /dev/videoN that opens AND reports V4L2 VIDEO_CAPTURE (skip sensorless ISI nodes)."""
    VIDIOC_QUERYCAP = 0x80685600
    for path in sorted(glob.glob("/dev/video*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
            if struct.unpack_from("<I", buf, 84)[0] & 0x00000001:
                return path
        except OSError:
            continue
        finally:
            os.close(fd)
    return None


_cam_env = os.environ.get("CAMERA_DEVICE", "auto")
CAMERA = _cam_env if _cam_env and _cam_env != "auto" else (_pick_camera() or "/dev/video0")


def _wayland_available():
    rt = os.environ.get("XDG_RUNTIME_DIR", "")
    disp = os.environ.get("WAYLAND_DISPLAY", "wayland-1")
    if not rt:
        return False
    return os.path.exists(disp if os.path.isabs(disp) else os.path.join(rt, disp))


_use_disp = os.environ.get("USE_DISPLAY", "auto").lower()
if _use_disp in ("1", "true", "yes"):
    USE_DISPLAY = True
elif _use_disp in ("0", "false", "no"):
    USE_DISPLAY = False
else:
    USE_DISPLAY = _wayland_available()


# --- shared state ------------------------------------------------------------
_kp_lock = threading.Lock()
_keypoints = None  # np.ndarray [17,3] = (y, x, score) normalized 0..1

_web_lock = threading.Lock()
_web_frame = None


class Stats:
    def __init__(self):
        self.n = 0
        self.t0 = time.monotonic()
        self.fps = 0.0


stats = Stats()


def on_pose(_sink, buffer, _ud):
    """tensor_sink: MoveNet output [1,1,17,3] float32 -> store 17 (y,x,score)."""
    mem = buffer.peek_memory(0)
    ok, info = mem.map(Gst.MapFlags.READ)
    if not ok:
        return
    try:
        kp = np.frombuffer(info.data, dtype=np.float32).reshape(-1, 3)[:17].copy()
    finally:
        mem.unmap(info)

    with _kp_lock:
        global _keypoints
        _keypoints = kp

    stats.n += 1
    dt = time.monotonic() - stats.t0
    if dt >= 1.0:
        stats.fps = stats.n / dt
        stats.n = 0
        stats.t0 = time.monotonic()
        n_vis = int((kp[:, 2] > SCORE_THRESH).sum())
        print(f"[{'NPU' if USE_NPU else 'CPU'} {stats.fps:4.1f} fps] {n_vis}/17 keypoints", flush=True)


def on_draw(_overlay, cr, _ts, _dur):
    """cairooverlay draw: render the skeleton onto the (square) preview frame."""
    with _kp_lock:
        kp = None if _keypoints is None else _keypoints.copy()
    if kp is None:
        return
    s = PREVIEW
    # edges
    cr.set_line_width(4.0)
    cr.set_source_rgb(0.0, 1.0, 0.4)
    for a, b in EDGES:
        if kp[a, 2] > SCORE_THRESH and kp[b, 2] > SCORE_THRESH:
            cr.move_to(kp[a, 1] * s, kp[a, 0] * s)
            cr.line_to(kp[b, 1] * s, kp[b, 0] * s)
            cr.stroke()
    # joints
    cr.set_source_rgb(1.0, 0.2, 0.2)
    for i in range(17):
        if kp[i, 2] > SCORE_THRESH:
            cr.arc(kp[i, 1] * s, kp[i, 0] * s, 5.0, 0, 2 * 3.14159265)
            cr.fill()


# --- web (MJPEG over HTTP) ----------------------------------------------------
def on_web_sample(appsink):
    sample = appsink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.OK
    buf = sample.get_buffer()
    ok, info = buf.map(Gst.MapFlags.READ)
    if ok:
        try:
            with _web_lock:
                global _web_frame
                _web_frame = bytes(info.data)
        finally:
            buf.unmap(info)
    return Gst.FlowReturn.OK


class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (
                b"<!doctype html><html><head><title>i.MX8MP NPU pose</title></head>"
                b"<body style='margin:0;background:#111'>"
                b"<img src='/stream' style='width:100vw;height:100vh;object-fit:contain'>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _web_lock:
                        frame = _web_frame
                    if frame is not None:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    time.sleep(1 / 30.0)
            except (BrokenPipeError, ConnectionResetError):
                return
        self.send_error(404)


def start_web_server(port):
    srv = ThreadingHTTPServer(("0.0.0.0", port), _MJPEGHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    Gst.init(None)
    if USE_NPU and not os.path.exists(VX_DELEGATE):
        print(f"WARNING: {VX_DELEGATE} missing; the model will run on CPU", file=sys.stderr)

    tfilter = f"framework=tensorflow-lite model={MODEL}"
    if USE_NPU:
        tfilter += f" custom=Delegate:External,ExtDelegateLib:{VX_DELEGATE}"

    web = WEB_PORT > 0
    # Crop to a centered square so keypoint coords (normalized) map straight to pixels.
    src = (
        f"v4l2src device={CAMERA} ! video/x-raw,framerate=30/1 ! videoconvert "
        f"! aspectratiocrop aspect-ratio=1/1 ! videoscale "
        f"! video/x-raw,format=RGB,width={PREVIEW},height={PREVIEW} ! tee name=t "
    )
    # inference branch (always). tensor_converter emits uint8; MoveNet's input is
    # int32 (its SavedModel input dtype, which survives full-INT8 conversion), so
    # widen uint8 0..255 -> int32 0..255 to match. (Pure typecast, values intact.)
    desc = src + (
        f"t. ! queue max-size-buffers=2 leaky=downstream "
        f"! videoscale ! video/x-raw,format=RGB,width={INPUT},height={INPUT} "
        f"! tensor_converter ! tensor_transform mode=typecast option=int32 "
        f"! tensor_filter {tfilter} ! tensor_sink name=res "
    )
    # preview branch (skeleton overlay) -> display and/or web
    if USE_DISPLAY or web:
        desc += (
            f"t. ! queue max-size-buffers=2 leaky=downstream "
            f"! videoconvert ! video/x-raw,format=BGRx ! cairooverlay name=draw ! tee name=t2 "
        )
        if USE_DISPLAY:
            desc += "t2. ! queue ! videoconvert ! waylandsink sync=false "
        if web:
            desc += "t2. ! queue ! videoconvert ! jpegenc quality=70 ! appsink name=web emit-signals=true max-buffers=1 drop=true "

    modes = (["display"] if USE_DISPLAY else []) + ([f"web :{WEB_PORT}"] if web else [])
    print(f"Mode: {', '.join(modes) or 'headless'}  Camera: {CAMERA}  Backend: {'NPU' if USE_NPU else 'CPU'}", flush=True)
    print("Pipeline:\n  " + desc.replace("! ", "!\n      "), flush=True)

    pipeline = Gst.parse_launch(desc)
    pipeline.get_by_name("res").connect("new-data", on_pose, None)

    draw = pipeline.get_by_name("draw")
    if draw is not None:
        draw.connect("draw", on_draw)

    web_appsink = pipeline.get_by_name("web")
    if web_appsink is not None:
        web_appsink.connect("new-sample", on_web_sample)
        start_web_server(WEB_PORT)
        print(f"Web preview: http://0.0.0.0:{WEB_PORT}/", flush=True)

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_msg(_bus, msg):
        if msg.type == Gst.MessageType.EOS:
            loop.quit()
        elif msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"ERROR: {err} ({dbg})", file=sys.stderr, flush=True)
            loop.quit()

    bus.connect("message", on_msg)
    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
