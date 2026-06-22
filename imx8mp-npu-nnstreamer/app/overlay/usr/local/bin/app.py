#!/usr/bin/env python3
"""Live MobileNet INT8 camera classification on the i.MX8M Plus NPU.

NNStreamer pipeline (a single camera tee feeds the inference path plus any
enabled previews):

    v4l2src -> tee --+--> textoverlay -> waylandsink            (USE_DISPLAY: local view)
                     +--> textoverlay -> jpegenc -> appsink     (WEB_PORT: browser view)
                     +--> videoscale 224 -> tensor_converter
                          -> tensor_filter (TFLite, INT8) -> tensor_sink  (label + fps)

The inference path is always present and identical; previews are optional. With
no preview enabled the pipeline collapses to camera -> inference -> tensor_sink
and labels go to stdout/journal only (cheapest headless benchmark).

Web preview: when WEB_PORT > 0 the app serves an MJPEG stream over HTTP at
http://<board>:<WEB_PORT>/ -- the live camera with the NPU label overlaid, in
any browser, no compositor/display required. This is the way to "see" the demo
on a headless board (e.g. the gateway).

NPU offload is one knob: when USE_NPU=1 the tensor_filter loads the Vivante VX
external delegate (libvx_delegate.so -> tim-vx -> imx-gpu-viv/libOpenVX ->
galcore -> VIP NPU). Set USE_NPU=0 to run the same model on the CPU and compare
the FPS.

Env:
  MODEL          path to the INT8 .tflite      (default: the installed model)
  LABELS         path to labels.txt
  CAMERA_DEVICE  v4l2 device or "auto"          (default: auto = first capture node)
  CAM_WIDTH/CAM_HEIGHT  preview size            (default: 640x480)
  USE_NPU        1 = VX delegate (NPU), 0 = CPU (default: 1)
  USE_DISPLAY    1 = force waylandsink view, 0 = force headless,
                 auto (default) = use the view only if a Wayland socket exists
  WEB_PORT       MJPEG-over-HTTP preview port, 0 = off (default: 8080)
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
from gi.repository import GLib, Gst  # noqa: E402

APPDIR = "/usr/lib/imx8mp-npu-nnstreamer"
MODEL = os.environ.get("MODEL", f"{APPDIR}/mobilenet_v2_int8.tflite")
LABELS = os.environ.get("LABELS", f"{APPDIR}/labels.txt")


def _pick_camera():
    """First /dev/videoN that opens AND reports V4L2 VIDEO_CAPTURE.

    On i.MX8MP the on-chip ISI capture nodes occupy /dev/video0,1 but EBUSY on
    open when no CSI sensor is wired, while a USB UVC webcam lands on a higher
    node (e.g. /dev/video2). A fixed default is therefore wrong board-to-board;
    probe instead. VIDIOC_QUERYCAP = _IOR('V',0, struct v4l2_capability[104]);
    device_caps is at byte 84, V4L2_CAP_VIDEO_CAPTURE = 0x1.
    """
    VIDIOC_QUERYCAP = 0x80685600
    for path in sorted(glob.glob("/dev/video*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue  # busy / unusable (e.g. sensorless ISI node)
        try:
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
            device_caps = struct.unpack_from("<I", buf, 84)[0]
            if device_caps & 0x00000001:
                return path
        except OSError:
            continue
        finally:
            os.close(fd)
    return None


_cam_env = os.environ.get("CAMERA_DEVICE", "auto")
CAMERA = _cam_env if _cam_env and _cam_env != "auto" else (_pick_camera() or "/dev/video0")
CW = os.environ.get("CAM_WIDTH", "640")
CH = os.environ.get("CAM_HEIGHT", "480")
USE_NPU = os.environ.get("USE_NPU", "1") == "1"
VX_DELEGATE = "/usr/lib/libvx_delegate.so"

try:
    WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
except ValueError:
    WEB_PORT = 0


def _wayland_available():
    """True if a Wayland compositor socket is reachable (XDG_RUNTIME_DIR/WAYLAND_DISPLAY)."""
    rt = os.environ.get("XDG_RUNTIME_DIR", "")
    disp = os.environ.get("WAYLAND_DISPLAY", "wayland-1")
    if not rt:
        return False
    sock = disp if os.path.isabs(disp) else os.path.join(rt, disp)
    return os.path.exists(sock)


_use_disp = os.environ.get("USE_DISPLAY", "auto").lower()
if _use_disp in ("1", "true", "yes"):
    USE_DISPLAY = True
elif _use_disp in ("0", "false", "no"):
    USE_DISPLAY = False
else:  # auto
    USE_DISPLAY = _wayland_available()

with open(LABELS) as f:
    labels = [ln.strip() for ln in f]


class Stats:
    def __init__(self):
        self.n = 0
        self.t0 = time.monotonic()
        self.fps = 0.0


stats = Stats()


# --- Web (MJPEG-over-HTTP) preview ------------------------------------------
_web_lock = threading.Lock()
_web_frame = None  # latest JPEG bytes from the appsink


def _set_web_frame(b):
    global _web_frame
    with _web_lock:
        _web_frame = b


def on_web_sample(appsink):
    """appsink new-sample: stash the latest JPEG for the HTTP stream."""
    sample = appsink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.OK
    buf = sample.get_buffer()
    ok, info = buf.map(Gst.MapFlags.READ)
    if ok:
        try:
            _set_web_frame(bytes(info.data))
        finally:
            buf.unmap(info)
    return Gst.FlowReturn.OK


class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass  # quiet

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (
                b"<!doctype html><html><head><title>i.MX8MP NPU</title></head>"
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
            self.send_header("Pragma", "no-cache")
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


def on_new_data(_sink, buffer, overlays):
    """tensor_sink callback: argmax the INT8 output -> label + FPS on each preview overlay."""
    mem = buffer.peek_memory(0)
    ok, info = mem.map(Gst.MapFlags.READ)
    if not ok:
        return
    try:
        out = np.frombuffer(info.data, dtype=np.uint8)
    finally:
        mem.unmap(info)

    top = int(out.argmax())
    label = labels[top] if top < len(labels) else f"class {top}"

    stats.n += 1
    dt = time.monotonic() - stats.t0
    if dt >= 1.0:
        stats.fps = stats.n / dt
        stats.n = 0
        stats.t0 = time.monotonic()

    backend = "NPU" if USE_NPU else "CPU"
    text = f"{label}   [{backend} {stats.fps:4.1f} fps]"
    for ov in overlays:
        ov.set_property("text", text)
    print(text, flush=True)


def main():
    Gst.init(None)

    if USE_NPU and not os.path.exists(VX_DELEGATE):
        print(f"WARNING: {VX_DELEGATE} missing; the model will run on CPU", file=sys.stderr)

    # tensor_filter properties. The VX external delegate is the NPU offload.
    tfilter = f"framework=tensorflow-lite model={MODEL}"
    if USE_NPU:
        tfilter += f" custom=Delegate:External,ExtDelegateLib:{VX_DELEGATE}"

    web = WEB_PORT > 0
    preview = USE_DISPLAY or web

    if preview:
        # Capture at preview size, tee to the inference path + each enabled preview.
        desc = (
            f"v4l2src device={CAMERA} ! video/x-raw,framerate=30/1 "
            f"! videoconvert ! videoscale "
            f"! video/x-raw,format=RGB,width={CW},height={CH} ! tee name=t "
            # inference branch
            f"t. ! queue max-size-buffers=2 leaky=downstream "
            f"! videoscale ! video/x-raw,format=RGB,width=224,height=224 "
            f"! tensor_converter ! tensor_filter {tfilter} ! tensor_sink name=res "
        )
        if USE_DISPLAY:
            desc += (
                f"t. ! queue max-size-buffers=2 leaky=downstream "
                f'! textoverlay name=label valignment=top halignment=left font-desc="Sans, 20" '
                f"! videoconvert ! waylandsink sync=false "
            )
        if web:
            desc += (
                f"t. ! queue max-size-buffers=2 leaky=downstream "
                f'! textoverlay name=weblabel valignment=top halignment=left font-desc="Sans, 20" '
                f"! videoconvert ! jpegenc quality=70 "
                f"! appsink name=web emit-signals=true max-buffers=1 drop=true "
            )
        pipeline_desc = desc
    else:
        # Pure headless: inference path only, results to journal.
        pipeline_desc = (
            f"v4l2src device={CAMERA} ! video/x-raw,framerate=30/1 "
            f"! videoconvert ! videoscale "
            f"! video/x-raw,format=RGB,width=224,height=224 "
            f"! tensor_converter ! tensor_filter {tfilter} ! tensor_sink name=res"
        )

    modes = []
    if USE_DISPLAY:
        modes.append("display")
    if web:
        modes.append(f"web :{WEB_PORT}")
    if not modes:
        modes.append("headless")
    print(f"Mode: {', '.join(modes)}  Camera: {CAMERA}", flush=True)
    print("Pipeline:\n  " + pipeline_desc.replace("! ", "!\n      "), flush=True)

    pipeline = Gst.parse_launch(pipeline_desc)
    overlays = [o for o in (pipeline.get_by_name("label"), pipeline.get_by_name("weblabel")) if o is not None]
    pipeline.get_by_name("res").connect("new-data", on_new_data, overlays)

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
