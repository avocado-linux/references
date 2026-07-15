#!/usr/bin/env python3

import sys
sys.path.insert(0, "/usr/lib/app/packages")

import time
import threading

import cv2
import numpy as np
import pyrealsense2 as rs
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# RealSense pipeline (shared across all streams)
# ---------------------------------------------------------------------------

pipeline = None
align = None
colorizer = None
device_info = {}
lock = threading.Lock()

latest = {
    "color": None,
    "depth_colormap": None,
    "infrared": None,
    "depth_raw": None,        # numpy uint16 depth in sensor units
    "depth_scale": 0.001,     # metres per unit
    "depth_intrinsics": None,
}


def start_pipeline():
    global pipeline, align, colorizer, device_info

    pipeline = rs.pipeline()
    cfg = rs.config()

    # 15 fps keeps all three streams within USB 2.0 bandwidth.
    # At 30 fps the depth frames silently freeze (duplicate data).
    cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
    cfg.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)
    cfg.enable_stream(rs.stream.infrared, 1, 640, 480, rs.format.y8, 15)

    profile = pipeline.start(cfg)

    align = rs.align(rs.stream.color)

    # Jet colour map — vivid red/yellow/green/blue depth visualisation
    colorizer = rs.colorizer()
    colorizer.set_option(rs.option.color_scheme, 0)

    dev = profile.get_device()
    device_info["name"] = dev.get_info(rs.camera_info.name)
    device_info["serial"] = dev.get_info(rs.camera_info.serial_number)
    device_info["firmware"] = dev.get_info(rs.camera_info.firmware_version)
    device_info["usb"] = (
        dev.get_info(rs.camera_info.usb_type_descriptor)
        if dev.supports(rs.camera_info.usb_type_descriptor)
        else "N/A"
    )

    depth_sensor = dev.first_depth_sensor()
    scale = depth_sensor.get_depth_scale()
    device_info["depth_scale"] = scale
    device_info["laser_power"] = (
        depth_sensor.get_option(rs.option.laser_power)
        if depth_sensor.supports(rs.option.laser_power)
        else "N/A"
    )

    with lock:
        latest["depth_scale"] = scale

    print(
        f"RealSense started: {device_info['name']} (S/N {device_info['serial']})",
        flush=True,
    )


def capture_loop():
    while True:
        try:
            frames = pipeline.wait_for_frames(timeout_ms=5000)
        except RuntimeError:
            continue

        aligned = align.process(frames)

        color_frame = aligned.first(rs.stream.color)
        depth_frame = aligned.first(rs.stream.depth)
        ir_frame = frames.first(rs.stream.infrared)

        if not color_frame or not depth_frame:
            continue

        color_image = np.array(color_frame.get_data())
        depth_raw = np.array(depth_frame.get_data())

        # Use rs.colorizer then .copy() — the colorizer's internal buffer
        # is reused across calls, so we must copy before the next colorize().
        depth_image = np.array(colorizer.colorize(depth_frame).get_data()).copy()

        ir_image = None
        if ir_frame:
            ir_image = cv2.cvtColor(np.array(ir_frame.get_data()), cv2.COLOR_GRAY2BGR)

        depth_intrinsics = depth_frame.profile.as_video_stream_profile().intrinsics

        with lock:
            latest["color"] = color_image
            latest["depth_colormap"] = depth_image
            latest["infrared"] = ir_image
            latest["depth_raw"] = depth_raw
            latest["depth_intrinsics"] = depth_intrinsics


# ---------------------------------------------------------------------------
# MJPEG streaming
# ---------------------------------------------------------------------------

def gen_mjpeg(frame_key):
    while True:
        with lock:
            frame = latest.get(frame_key)

        if frame is None:
            time.sleep(0.05)
            continue

        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )
        time.sleep(0.033)


def _feed(key):
    return Response(
        gen_mjpeg(key),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Pragma": "no-cache", "Expires": "0"},
    )


@app.route("/feed/color")
def feed_color():
    return _feed("color")

@app.route("/feed/depth")
def feed_depth():
    return _feed("depth_colormap")

@app.route("/feed/infrared")
def feed_infrared():
    return _feed("infrared")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/device")
def api_device():
    return jsonify(device_info)


@app.route("/api/distance")
def api_distance():
    x = request.args.get("x", type=int)
    y = request.args.get("y", type=int)

    if x is None or y is None:
        return jsonify({"error": "x and y query params required"}), 400

    with lock:
        depth_raw = latest.get("depth_raw")
        intrinsics = latest.get("depth_intrinsics")
        scale = latest.get("depth_scale", 0.001)

    if depth_raw is None or intrinsics is None:
        return jsonify({"error": "no depth data available"}), 503

    x = max(0, min(x, intrinsics.width - 1))
    y = max(0, min(y, intrinsics.height - 1))

    distance = float(depth_raw[y, x]) * scale
    point = rs.rs2_deproject_pixel_to_point(intrinsics, [float(x), float(y)], distance)

    return jsonify({
        "x": x,
        "y": y,
        "distance_m": round(distance, 3),
        "point_3d": [round(p, 4) for p in point],
    })


@app.route("/api/stream_info")
def api_stream_info():
    with lock:
        intrinsics = latest.get("depth_intrinsics")
    if intrinsics is None:
        return jsonify({"width": 640, "height": 480})
    return jsonify({"width": intrinsics.width, "height": intrinsics.height})


# ---------------------------------------------------------------------------
# Dashboard — 3 panels: Color, Depth, Infrared
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RealSense Visualizer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0b0d11;--card:#13161d;--card2:#191c25;--border:#252835;
  --text:#e2e5ef;--muted:#7a7f95;--accent:#4a9eff;--accent2:#7c4dff;
  --green:#22c55e;--orange:#f59e0b;--red:#ef4444;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

header{background:var(--card);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;gap:14px}
header h1{font-size:18px;font-weight:700;letter-spacing:-.3px}
.badge{font-size:10px;padding:3px 10px;border-radius:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.badge-live{background:var(--green);color:#fff}
.badge-err{background:var(--red);color:#fff}

.device-bar{background:var(--card);border-bottom:1px solid var(--border);padding:8px 24px;display:flex;gap:24px;font-size:12px;color:var(--muted);flex-wrap:wrap}
.device-bar b{color:var(--text);font-weight:600}

.toggle-bar{background:var(--card2);border-bottom:1px solid var(--border);padding:10px 24px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.toggle-bar .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-right:8px;font-weight:600}
.tbtn{
  border:1px solid var(--border);background:transparent;color:var(--muted);
  font-size:12px;font-weight:600;padding:6px 16px;border-radius:6px;cursor:pointer;
  transition:all .15s ease;display:flex;align-items:center;gap:6px;
}
.tbtn:hover{border-color:var(--accent);color:var(--text)}
.tbtn.active{background:var(--accent);border-color:var(--accent);color:#fff}
.tbtn .dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot-color{background:var(--green)}.dot-depth{background:var(--accent)}.dot-ir{background:var(--orange)}.dot-dist{background:var(--red)}

.grid{display:grid;gap:14px;padding:14px 24px;max-width:1600px;margin:0 auto;transition:all .2s ease}
.grid.cols-1{grid-template-columns:1fr}
.grid.cols-2{grid-template-columns:1fr 1fr}
.grid.cols-3{grid-template-columns:1fr 1fr 1fr}

.panel{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:none}
.panel.visible{display:block}
.panel-head{padding:8px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:7px}
.panel img{width:100%;display:block;cursor:crosshair;background:#000;aspect-ratio:4/3;object-fit:contain}

.measure-bar{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:12px 24px;display:none;align-items:center;gap:28px;
}
.measure-bar.visible{display:flex}
.measure-bar .ml{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
.measure-bar .mv{font-size:32px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--accent);min-width:130px;line-height:1.1}
.measure-bar .mc{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.measure-bar .m3{color:var(--muted);font-size:13px;font-family:'SF Mono',SFMono-Regular,Consolas,monospace}
.measure-hint{color:var(--muted);font-size:11px;margin-left:auto;opacity:.7}

@media(max-width:900px){.grid{grid-template-columns:1fr!important}}
</style>
</head>
<body>

<header>
  <h1>RealSense Visualizer</h1>
  <div class="badge badge-err" id="status">CONNECTING</div>
</header>

<div class="device-bar" id="deviceBar">Waiting for camera&hellip;</div>

<div class="toggle-bar">
  <span class="label">Views</span>
  <button class="tbtn active" data-panel="color"   onclick="toggle('color')">  <span class="dot dot-color"></span>Color</button>
  <button class="tbtn active" data-panel="depth"   onclick="toggle('depth')">  <span class="dot dot-depth"></span>Depth</button>
  <button class="tbtn active" data-panel="ir"      onclick="toggle('ir')">     <span class="dot dot-ir"></span>Infrared</button>
  <button class="tbtn active" data-panel="dist"    onclick="toggle('dist')">   <span class="dot dot-dist"></span>Distance</button>
</div>

<div class="measure-bar visible" id="p-dist">
  <div>
    <div class="ml">Distance</div>
    <div class="mv" id="distVal">&mdash;</div>
  </div>
  <div>
    <div class="ml">Pixel</div>
    <div class="mc" id="distCoords">&mdash;</div>
  </div>
  <div>
    <div class="ml">3D Point (m)</div>
    <div class="m3" id="dist3d">&mdash;</div>
  </div>
  <div class="measure-hint">Click any feed to measure depth</div>
</div>

<div class="grid cols-3" id="grid">

  <div class="panel visible" id="p-color">
    <div class="panel-head"><span class="dot dot-color"></span>Color Stream</div>
    <img data-src="/feed/color" src="/feed/color" alt="Color" onclick="measure(event,this)">
  </div>

  <div class="panel visible" id="p-depth">
    <div class="panel-head"><span class="dot dot-depth"></span>Depth Colormap</div>
    <img data-src="/feed/depth" src="/feed/depth" alt="Depth" onclick="measure(event,this)">
  </div>

  <div class="panel visible" id="p-ir">
    <div class="panel-head"><span class="dot dot-ir"></span>Infrared</div>
    <img data-src="/feed/infrared" src="/feed/infrared" alt="Infrared" onclick="measure(event,this)">
  </div>

</div>

<script>
const panels = ['color','depth','ir','dist'];
const state  = {};
panels.forEach(p => state[p] = true);

let streamW = 640, streamH = 480;

function toggle(id) {
  state[id] = !state[id];

  document.querySelector('[data-panel="'+id+'"]').classList.toggle('active', state[id]);
  var el = document.getElementById('p-'+id);
  el.classList.toggle('visible', state[id]);

  if (id !== 'dist') {
    var img = el.querySelector('img');
    if (state[id]) {
      img.src = img.dataset.src;
    } else {
      img.src = '';
    }
  }

  reflow();
}

function reflow() {
  var visible = ['color','depth','ir'].filter(k => state[k]).length;
  var g = document.getElementById('grid');
  g.classList.remove('cols-1','cols-2','cols-3');
  if (visible <= 1)      g.classList.add('cols-1');
  else if (visible <= 2) g.classList.add('cols-2');
  else                   g.classList.add('cols-3');
}

async function loadDevice() {
  try {
    var r = await fetch('/api/device');
    var d = await r.json();
    document.getElementById('deviceBar').innerHTML =
      'Camera: <b>'+d.name+'</b>'+
      ' &nbsp;|&nbsp; Serial: <b>'+d.serial+'</b>'+
      ' &nbsp;|&nbsp; FW: <b>'+d.firmware+'</b>'+
      ' &nbsp;|&nbsp; USB: <b>'+d.usb+'</b>'+
      ' &nbsp;|&nbsp; Depth scale: <b>'+d.depth_scale+'</b>';
    var s = document.getElementById('status');
    s.textContent = 'LIVE';
    s.className = 'badge badge-live';
  } catch(e) {
    var s = document.getElementById('status');
    s.textContent = 'ERROR';
    s.className = 'badge badge-err';
  }
}

async function loadStreamInfo() {
  try {
    var r = await fetch('/api/stream_info');
    var d = await r.json();
    streamW = d.width;
    streamH = d.height;
  } catch(e) {}
}

async function measure(ev, img) {
  if (!state.dist) return;
  var rect = img.getBoundingClientRect();
  var x = Math.round((ev.clientX - rect.left) * (streamW / rect.width));
  var y = Math.round((ev.clientY - rect.top)  * (streamH / rect.height));
  try {
    var r = await fetch('/api/distance?x='+x+'&y='+y);
    var d = await r.json();
    if (d.error) return;
    var dist = d.distance_m;
    document.getElementById('distVal').textContent =
      dist < 1 ? (dist*100).toFixed(1)+' cm' : dist.toFixed(3)+' m';
    document.getElementById('distCoords').textContent = '('+d.x+', '+d.y+')';
    document.getElementById('dist3d').textContent =
      'X='+d.point_3d[0]+'  Y='+d.point_3d[1]+'  Z='+d.point_3d[2];
  } catch(e){}
}

loadDevice();
loadStreamInfo();
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
    print("RealSense Visualizer starting...", flush=True)
    start_pipeline()
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()
    print("  Dashboard: http://0.0.0.0:5000", flush=True)
    app.run(host="0.0.0.0", port=5000, threaded=True)
