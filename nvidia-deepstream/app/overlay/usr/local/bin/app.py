#!/usr/bin/env python3
"""
NVIDIA DeepStream — Person Detection + Tracking + Analytics + Pose on Avocado OS.

Pipeline:
  v4l2src -> capsfilter -> jpegdec -> videoconvert ->
    nvvideoconvert -> nvstreammux -> nvinfer (PeopleNet) ->
    nvtracker (NvDCF) -> nvdsanalytics -> nvinfer (MoveNet, secondary) ->
    nvinfer (YOLOX-Hand, secondary) -> nvinfer (MediaPipe Hand Landmark,
    tertiary) -> nvvideoconvert -> nvdsosd -> nvjpegenc -> appsink
    (HW JPEG → Flask MJPEG)

A pad probe on nvdsosd's sink reads four kinds of metadata per buffer:
  - NvDsObjectMeta on each tracked object (detections + tracker IDs).
    This list now contains two object kinds: PeopleNet `Person/Face/Bag`
    detections (unique_component_id=1) and synthetic `Hand` children
    (unique_component_id=3) that we inject from the YOLOX tensor meta.
  - NvDsAnalyticsFrameMeta / NvDsAnalyticsObjInfo from nvdsanalytics
    (per-frame line-crossing counts, ROI memberships) — these still
    only attach to PeopleNet objects, not the synthetic hand ones.
  - NvDsInferTensorMeta from the MoveNet secondary GIE — the raw
    [1, 1, 17, 3] keypoint output. The probe projects each normalised
    (y, x) keypoint back into image-pixel coordinates using the person's
    bounding box and, while it has the data, attaches NvDsDisplayMeta
    line + circle params for the skeleton so nvdsosd rasterises the bones
    and joints into the same JPEG that streams out to Flask.
  - NvDsInferTensorMeta from the MediaPipe Hand Landmark tertiary GIE —
    `xyz_x21` (21 keypoints × xyz) + `hand_score` + handedness. Same
    projection-and-display-meta pattern as MoveNet, but spans two
    NvDsDisplayMeta objects per hand because 21 > the 16-shapes-per-kind
    cap on a single display meta.

A second pad probe sits on the YOLOX-Hand nvinfer's SRC pad. It runs
*between* the hand detector and the hand landmarker, decodes the
[1, 2100, 8] full-frame YOLOX tensor attached to `frame_user_meta_list`,
runs grid-decode + class-wise NMS + letterbox-aware coord mapping, and
emits one synthetic NvDsObjectMeta per surviving hand. Those objects
are what the tertiary landmark GIE then operates on — they carry the
hand bbox in image-space coordinates, and the landmark tensor meta is
attached back to them by nvinfer.

Per-frame state ends up surfaced as:
  - the live MJPEG stream with bounding boxes, ROI rectangles,
    skeletons, and hand keypoints all burned in by `nvdsosd` (no
    client-side rendering — the HTML toggles flip server-side flags via
    /api/toggle/{skeletons,zones,hands} that the pad probe consults
    each frame)
  - cumulative line-crossing counters and per-tracker ROI dwell timers
    (/api/stats)
  - per-detection body keypoints and per-hand finger keypoints in
    image-pixel coordinates (/api/stats), for downstream tools /
    debugging — the dashboard itself doesn't read them.
"""

import collections
import configparser
import ctypes
import logging
import math
import os
import sys
import threading
import time

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import pyds

from flask import Flask, Response, jsonify

# pyds in DeepStream 7.1 no longer exports UNTRACKED_OBJECT_ID at module level
# (older versions did). The underlying NvDsObjectMeta.object_id is set to
# UINT64_MAX (0xFFFFFFFFFFFFFFFF) when a detection has no tracker association.
# Fall back to that literal when the symbol isn't there.
_UNTRACKED_OBJECT_ID = getattr(pyds, "UNTRACKED_OBJECT_ID", 0xFFFFFFFFFFFFFFFF)

# ---------------------------------------------------------------------------
# Config (env-driven; systemd unit defines defaults)
# ---------------------------------------------------------------------------

DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
FRAMERATE = int(os.environ.get("CAMERA_FRAMERATE", "30"))
PORT = int(os.environ.get("PORT", "8080"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

INFER_CONFIG = os.environ.get(
    "INFER_CONFIG",
    "/etc/nvidia-deepstream/config_infer_peoplenet.txt",
)
TRACKER_CONFIG = os.environ.get(
    "TRACKER_CONFIG",
    "/etc/nvidia-deepstream/tracker_NvDCF.yml",
)
TRACKER_LIB = os.environ.get(
    "TRACKER_LIB",
    "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
)
ANALYTICS_CONFIG = os.environ.get(
    "ANALYTICS_CONFIG",
    "/etc/nvidia-deepstream/analytics_config.txt",
)
MOVENET_CONFIG = os.environ.get(
    "MOVENET_CONFIG",
    "/etc/nvidia-deepstream/config_infer_movenet.txt",
)
HANDDET_CONFIG = os.environ.get(
    "HANDDET_CONFIG",
    "/etc/nvidia-deepstream/config_infer_handdet.txt",
)
HANDLM_CONFIG = os.environ.get(
    "HANDLM_CONFIG",
    "/etc/nvidia-deepstream/config_infer_handlandmark.txt",
)
# Set to "0" via systemd drop-in to drop the secondary pose GIE from the
# pipeline entirely (e.g. to recover frame rate on a busy scene or to test
# without pose).
ENABLE_POSE = os.environ.get("ENABLE_POSE", "1") not in ("0", "false", "False", "")
# Drop the YOLOX-Hand secondary + MediaPipe Hand Landmark tertiary from the
# pipeline. Hands are heavier than the body skeleton (two extra GIEs, and
# the landmark inference fires once per detected hand per frame), so this
# toggle is here for users who want a leaner build.
ENABLE_HANDS = os.environ.get("ENABLE_HANDS", "1") not in ("0", "false", "False", "")

# gie-unique-id of the MoveNet secondary GIE — must match the value set in
# config_infer_movenet.txt. The pad probe filters tensor meta on this id so
# it doesn't try to interpret PeopleNet output (which is the same metadata
# type) as keypoints.
MOVENET_GIE_ID = 2
# Same idea for the YOLOX hand detector + MediaPipe hand landmarker. The
# detector emits the [N, 7] post-NMS tensor whose decoded boxes we inject as
# synthetic `Hand` NvDsObjectMeta children; the landmarker then operates on
# those and attaches its three-output landmark tensor to each.
HANDDET_GIE_ID = 3
HANDLM_GIE_ID = 4
# Class IDs from the YOLOX-BHH model: 0=body, 1=head, 2=hand. Only `hand` is
# of interest here — the body/head detections are noisier than PeopleNet's
# Person box and would clutter the dashboard.
HANDDET_HAND_CLASS_ID = 2
# YOLOX-BHH 320x320 (non-post export). Used to scale decoded pixel
# coords from model space → person-crop space → image space.
HANDDET_INPUT_SIZE = 320
# Drop hand detections below this confidence (`obj_score * cls_score`,
# both already sigmoid'd in the ONNX).
HANDDET_SCORE_THRESHOLD = float(os.environ.get("HANDDET_SCORE_THRESHOLD", "0.3"))
# IoU threshold for our NMS pass on the per-class hand detections.
HANDDET_NMS_IOU = 0.45

# YOLOX grid layout for a 320x320 input: three FPN levels with strides
# 8, 16, 32. Each level emits a flattened grid of anchors in raster order
# (row-major). Pre-compute the (grid_x, grid_y, stride) for every anchor
# so the decode is a single index lookup rather than a per-frame mod/div
# dance. Order matches the model's output: 40x40 first, then 20x20, then
# 10x10. Total 2100 anchors.
def _build_yolox_grid(input_size):
    grid = []
    for stride in (8, 16, 32):
        n = input_size // stride
        for gy in range(n):
            for gx in range(n):
                grid.append((gx, gy, stride))
    return grid

_YOLOX_GRID = _build_yolox_grid(HANDDET_INPUT_SIZE)

# How much to pad each PeopleNet Person bbox outward before secondary
# GIEs crop it. Without padding, MoveNet only sees pixels inside the
# tight body crop — stretching arms outward puts wrists outside the
# detection bbox and the body skeleton snaps inward at the bbox edge.
# Padding ~30% width / ~15% height covers normal arm extension at
# webcam distance without distorting body crop's aspect ratio so far
# that the pose model loses scale calibration.
PERSON_BBOX_PAD_X = float(os.environ.get("PERSON_BBOX_PAD_X", "0.30"))
PERSON_BBOX_PAD_Y = float(os.environ.get("PERSON_BBOX_PAD_Y", "0.15"))

# Limit the number of synthetic Hand objects we inject per frame. With
# 16-shape NvDsDisplayMeta cap, 21 keypoints per hand spans 2 display
# metas — letting an unbounded number of hands through risks blowing the
# 1024-objects-per-frame DS soft limit on busy scenes.
HANDDET_MAX_PER_FRAME = 4
# Hand-landmark output is in 224x224 model-input pixel space. Scaled
# down to 0..1 then up to the hand bbox to land in image coordinates.
HANDLM_INPUT_SIZE = 224
# Drop a whole hand when the landmarker's `hand_score` falls below this
# (i.e. the YOLOX bbox was a false positive — usually a face or a fist
# at an extreme angle).
HAND_PRESENCE_THRESHOLD = 0.5

# Confidence threshold for individual keypoints. Anything below this is
# treated as "not detected" — the keypoint is omitted from the skeleton so
# we don't draw lines flailing off-screen.
KEYPOINT_CONFIDENCE = 0.30

# COCO 17-keypoint topology MoveNet emits.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]
# Pairs of keypoint indices to connect with line segments. This gives the
# classic "stick figure": head/face links, shoulders, two arms, torso,
# two legs.
SKELETON_EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 4),       # face links
    (5, 6),                                # shoulders
    (5, 7), (7, 9),                        # left arm
    (6, 8), (8, 10),                       # right arm
    (5, 11), (6, 12), (11, 12),            # torso
    (11, 13), (13, 15),                    # left leg
    (12, 14), (14, 16),                    # right leg
]

# MediaPipe Hands 21-keypoint topology. Index 0 is the wrist; each finger
# occupies a contiguous block of 4 keypoints (MCP, PIP, DIP, TIP for the
# four non-thumb digits; CMC, MCP, IP, TIP for the thumb).
HAND_KEYPOINT_NAMES = [
    "wrist",
    "thumb_cmc",   "thumb_mcp",  "thumb_ip",   "thumb_tip",
    "index_mcp",   "index_pip",  "index_dip",  "index_tip",
    "middle_mcp",  "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp",    "ring_pip",   "ring_dip",   "ring_tip",
    "pinky_mcp",   "pinky_pip",  "pinky_dip",  "pinky_tip",
]
# 21 edges = 5 fingers × 4 joint links (3 inter-knuckle + 1 attach-to-palm)
# + 1 palm-arc closure across the base of the pinky and thumb. Matches the
# MediaPipe Hands canonical drawing topology.
HAND_SKELETON_EDGES = [
    # thumb (0 -> 1 -> 2 -> 3 -> 4)
    (0, 1), (1, 2), (2, 3), (3, 4),
    # index finger (0 -> 5 -> 6 -> 7 -> 8)
    (0, 5), (5, 6), (6, 7), (7, 8),
    # middle finger (5 -> 9 -> 10 -> 11 -> 12) — base-link routes via index
    # MCP, matching MediaPipe's canonical hand connection set.
    (5, 9), (9, 10), (10, 11), (11, 12),
    # ring finger (9 -> 13 -> 14 -> 15 -> 16)
    (9, 13), (13, 14), (14, 15), (15, 16),
    # pinky (13 -> 17 -> 18 -> 19 -> 20)
    (13, 17), (17, 18), (18, 19), (19, 20),
    # palm closure (wrist -> pinky MCP) so the silhouette closes
    (0, 17),
]

ENGINE_DIR = "/var/lib/nvidia-deepstream/engines"

# Keep at most this many completed dwell records per ROI. Plenty for the
# dashboard's recent-dwell list; older entries roll off the deque.
DWELL_HISTORY_MAX = 50

DEVICE_ID = os.uname().nodename

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("app")
log_gst = logging.getLogger("gstreamer")
log_det = logging.getLogger("detector")

logging.getLogger("werkzeug").setLevel(
    logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.WARNING
)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_latest_frame = None
_frame_lock = threading.Lock()

_latest_objects = []
_latest_hands = []
_objects_lock = threading.Lock()

# Overlay toggles — read by the streaming thread (pad probe) on every
# buffer; flipped by the corresponding /api/toggle/<name> POST endpoints.
# Plain booleans are atomic under the GIL, so no lock needed for these.
#
# Both overlays are painted by `nvdsosd` from `NvDsDisplayMeta` the probe
# attaches per frame — toggling skips the attachment, which removes the
# overlay from the next frame onwards. Same mechanism for both, so the
# dashboard's two buttons behave identically.
#
# Default both off so the live MJPEG starts clean (just bounding boxes)
# and viewers can opt in to the overlays they want to see.
_pose_overlay_enabled = False
_zones_overlay_enabled = False
_hands_overlay_enabled = False

_stats = {
    "frame_count": 0,
    "total_detections": 0,
    "start_time": None,
    "last_frame_time": None,
    "inference_times_ms": collections.deque(maxlen=100),
    "active_track_ids": set(),
    "total_unique_tracks": 0,
}

# Analytics state from nvdsanalytics. Updated by the OSD pad probe; read by
# the /api/stats route. Guarded by _objects_lock (same lock that protects the
# detection list — they're filled in the same probe).
#
#   line_crossings: cumulative per-line-name counts, plus the running delta
#     of how many crossed on the current frame (for "burst" highlighting).
#   roi_active_dwell: {(roi_name, tracker_id) -> first_seen_monotonic}
#     for objects currently inside an ROI. Used to compute live elapsed time.
#   roi_completed_dwell: per-roi deque of finished dwells (most recent first).
#   roi_total_completed / roi_total_seconds: running aggregates for averaging.
_analytics = {
    "line_crossings_cum": collections.defaultdict(int),
    "line_crossings_last_frame": collections.defaultdict(int),
    # Set of every ROI name nvdsanalytics has reported, even when empty.
    # Lets the dashboard list configured zones from the first frame instead
    # of waiting for somebody to walk into one.
    "roi_known": set(),
    "roi_current_count": collections.defaultdict(int),
    # Per-ROI entry counter — increments the moment a (roi_name, tracker_id)
    # pair is seen for the first time. Distinct from `roi_total_completed`
    # (which increments on *exit*): `entries` is the live "how many people
    # have walked into this zone" number and is what the dashboard shows
    # most prominently.
    "roi_total_entries": collections.defaultdict(int),
    "roi_active_dwell": {},
    "roi_completed_dwell": collections.defaultdict(
        lambda: collections.deque(maxlen=DWELL_HISTORY_MAX)
    ),
    "roi_total_completed": collections.defaultdict(int),
    "roi_total_seconds": collections.defaultdict(float),
    "roi_max_seconds": collections.defaultdict(float),
}

# nvdsanalytics frame and object user-meta type names — looked up once at
# import time so the probe doesn't pay the cost on every buffer. These strings
# are stable across DS releases.
_ANALYTICS_FRAME_META_TYPE = pyds.nvds_get_user_meta_type("NVIDIA.DSANALYTICSFRAME.USER_META")
_ANALYTICS_OBJ_META_TYPE = pyds.nvds_get_user_meta_type("NVIDIA.DSANALYTICSOBJ.USER_META")
# nvinfer attaches secondary-GIE output tensors with this fixed meta type.
# In DS 7.x pyds exports it as `pyds.NvDsMetaType.NVDSINFER_TENSOR_OUTPUT_META`
# (also re-exported at module level). Its enum members compare equal to the
# raw int value, so direct == in the probe works either way.
_TENSOR_META_TYPE = getattr(pyds, "NVDSINFER_TENSOR_OUTPUT_META", 12)


# ---------------------------------------------------------------------------
# MoveNet output handling
# ---------------------------------------------------------------------------

def _read_movenet_keypoints(tensor_meta, rect_params):
    """Decode a MoveNet tensor-meta blob into a list of image-space keypoints.

    The MoveNet output tensor is `[1, 1, 17, 3]` of float32 — 17 COCO
    keypoints, each `(y_norm, x_norm, confidence)`, with the coordinates
    expressed as fractions of the model's 192x192 input. Since nvinfer ran
    the secondary GIE on this object's bbox crop, we project the normalized
    coords back into the original frame's pixel space using the bbox.

    Returns None if the tensor isn't readable; otherwise a list of 17 dicts
    (or None entries for low-confidence keypoints):
        {"name": "left_shoulder", "x": 612, "y": 287, "confidence": 0.94}
    """
    if tensor_meta.num_output_layers < 1:
        return None

    # pyds exposes the per-layer buffers as `out_buf_ptrs_host` — a `void**`
    # array wrapped in a PyCapsule, one entry per output layer. `get_ptr`
    # gives us the int address of the void** array; we then walk it with
    # ctypes to pull the address of layer 0's actual data, then re-cast to
    # a float* for the keypoint values. (NvDsInferLayerInfo.buffer also
    # exists but reads as 0 on DS 7.1 in this configuration; the host-side
    # pointer array is the documented path.)
    arr_addr = pyds.get_ptr(tensor_meta.out_buf_ptrs_host)
    if not arr_addr:
        return None
    void_arr = ctypes.cast(int(arr_addr), ctypes.POINTER(ctypes.c_void_p))
    layer_addr = void_arr[0]
    if not layer_addr:
        return None
    ptr = ctypes.cast(int(layer_addr), ctypes.POINTER(ctypes.c_float))

    left, top = float(rect_params.left), float(rect_params.top)
    width, height = float(rect_params.width), float(rect_params.height)

    keypoints = []
    for i in range(17):
        y_norm = ptr[i * 3 + 0]
        x_norm = ptr[i * 3 + 1]
        conf = ptr[i * 3 + 2]
        # Drop low-confidence keypoints to None so neither the JSON
        # response nor `_draw_skeleton` paints flailing artifacts.
        # `_draw_skeleton` additionally suppresses any bone whose endpoint
        # is None.
        if conf < KEYPOINT_CONFIDENCE:
            keypoints.append(None)
            continue
        keypoints.append({
            "name": KEYPOINT_NAMES[i],
            "x": int(left + x_norm * width),
            "y": int(top + y_norm * height),
            "confidence": round(float(conf), 3),
        })
    return keypoints


# Max shapes per NvDsDisplayMeta. The DS C header pins this at 16 per kind
# (NvOSD_FrameLineParams::num_lines etc.); if a frame needs more, allocate
# additional display_meta objects and add each to the frame separately.
_DISPLAY_META_CAP = 16


def _clamp_xy(x, y):
    """Clamp a keypoint to non-negative ints inside the configured frame.

    NvOSD_CircleParams.xc/yc and NvOSD_LineParams.x1/x2/y1/y2 are `guint`
    in the DS C headers, so pyds rejects negative ints with a TypeError
    that takes down the pad probe. Keypoints projected from a person
    bbox can land outside the frame when MoveNet (or Hand Landmark)
    extrapolates beyond the crop — clamp here so the line/circle just
    draws at the frame edge instead of crashing the probe.
    """
    return (
        max(0, min(WIDTH - 1, int(x))),
        max(0, min(HEIGHT - 1, int(y))),
    )


def _draw_skeleton(batch_meta, frame_meta, keypoints, color):
    """Paint a person's skeleton onto the frame via NvDsDisplayMeta.

    `nvdsosd` downstream consumes whatever display meta we attach here and
    rasterises it onto the buffer before `nvjpegenc` encodes the JPEG. The
    skeleton therefore travels with the video frame at the full pipeline
    rate (no client-side polling, no MJPEG/SVG sync issue).

    `color` is a tuple of (r, g, b, a) in 0..1 — typically the same as the
    bbox border color so the joint colour matches the box around the person.
    """
    # Acquire a display_meta from batch_meta's pool. Up to _DISPLAY_META_CAP
    # of each shape kind fits per display_meta object; 17 keypoints + ~16
    # skeleton edges per person comfortably fits.
    display_meta = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
    r, g, b, a = color

    # Joints — small filled circles at every detected keypoint.
    n_circ = 0
    for kp in keypoints:
        if kp is None or n_circ >= _DISPLAY_META_CAP:
            continue
        c = display_meta.circle_params[n_circ]
        c.xc, c.yc = _clamp_xy(kp["x"], kp["y"])
        c.radius = 5
        c.has_bg_color = 1
        # circle_color is the outline; bg_color fills the disc.
        c.circle_color.set(r, g, b, a)
        c.bg_color.set(r, g, b, a)
        n_circ += 1
    display_meta.num_circles = n_circ

    # Bones — line segments between connected keypoints from the COCO
    # 17-keypoint topology. Edges where either endpoint is missing are
    # skipped so the figure doesn't sprout phantom limbs into the frame
    # origin.
    n_line = 0
    for a_idx, b_idx in SKELETON_EDGES:
        if n_line >= _DISPLAY_META_CAP:
            break
        a_kp = keypoints[a_idx]
        b_kp = keypoints[b_idx]
        if a_kp is None or b_kp is None:
            continue
        ln = display_meta.line_params[n_line]
        ln.x1, ln.y1 = _clamp_xy(a_kp["x"], a_kp["y"])
        ln.x2, ln.y2 = _clamp_xy(b_kp["x"], b_kp["y"])
        ln.line_width = 3
        ln.line_color.set(r, g, b, a)
        n_line += 1
    display_meta.num_lines = n_line

    pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)


def _draw_zone(batch_meta, frame_meta, name, polygon, entry_count):
    """Paint a zone polygon outline + "Name: count" label onto the frame.

    Same NvDsDisplayMeta path as `_draw_skeleton` — `nvdsosd` rasterises
    the result before `nvjpegenc` encodes the JPEG, so the rectangle and
    its live counter ride inside the MJPEG stream at the full pipeline
    rate. Polygon edges connect successive vertices (wrapping at the end),
    so an N-vertex polygon produces N line segments.
    """
    display_meta = pyds.nvds_acquire_display_meta_from_pool(batch_meta)

    # Lime-green accent matching the dashboard's primary color (#84cc16),
    # in 0..1 RGBA. Same shade used to highlight tracker IDs and counters
    # elsewhere in the UI.
    color = (0.52, 0.80, 0.09, 1.0)

    n_points = len(polygon)
    n_lines = 0
    for i in range(n_points):
        if n_lines >= _DISPLAY_META_CAP:
            break
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n_points]
        ln = display_meta.line_params[n_lines]
        ln.x1 = int(x1)
        ln.y1 = int(y1)
        ln.x2 = int(x2)
        ln.y2 = int(y2)
        ln.line_width = 3
        ln.line_color.set(*color)
        n_lines += 1
    display_meta.num_lines = n_lines

    # Label at the top-left vertex: "<Name>: <count>". nvdsosd renders text
    # with Cairo on Tegra — works for the handful of zones we have without
    # measurable cost.
    text = display_meta.text_params[0]
    text.display_text = f"{name}: {entry_count}"
    text.x_offset = int(polygon[0][0]) + 10
    text.y_offset = int(polygon[0][1]) + 10
    text.font_params.font_name = "Serif"
    text.font_params.font_size = 14
    text.font_params.font_color.set(*color)
    text.set_bg_clr = 1
    text.text_bg_clr.set(0.0, 0.0, 0.0, 0.6)
    display_meta.num_labels = 1

    pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)


# ---------------------------------------------------------------------------
# YOLOX hand-detector tensor decode + Hand object injection
# ---------------------------------------------------------------------------

def _yolox_iou(a, b):
    """Axis-aligned IoU of two (x1, y1, x2, y2) boxes."""
    ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
    iw = ix2 - ix1
    ih = iy2 - iy1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    aw = a[2] - a[0]; ah = a[3] - a[1]
    bw = b[2] - b[0]; bh = b[3] - b[1]
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _yolox_nms(per_class, iou_thresh):
    """Greedy NMS per class. `per_class` is a dict cls -> list of
    (score, x1, y1, x2, y2). Returns flat list of (cls, score, x1..y2)."""
    out = []
    for cls, rows in per_class.items():
        rows.sort(key=lambda r: -r[0])
        kept = []
        for r in rows:
            if any(_yolox_iou(r[1:], k[1:]) >= iou_thresh for k in kept):
                continue
            kept.append(r)
        for score, x1, y1, x2, y2 in kept:
            out.append((cls, score, x1, y1, x2, y2))
    return out


def _read_yolox_detections(tensor_meta):
    """Decode YOLOX-BHH non-post output into image-space detections.

    The model emits `[1, 2100, 8]` of raw head output:
        cx_grid, cy_grid, w_log, h_log, obj_sigmoid, c0, c1, c2

    cx_grid/cy_grid are offsets within an anchor cell; w_log/h_log are
    log-space deltas. To get pixel-space coords we add the anchor's
    grid position and multiply by its stride (the model has three FPN
    levels — 8, 16, 32 — laid out 40x40, then 20x20, then 10x10 in
    raster order; see `_YOLOX_GRID`).

    Per-anchor confidence is `obj * cls_score`. We threshold at
    HANDDET_SCORE_THRESHOLD, bucket by class, run a Python NMS at
    HANDDET_NMS_IOU, and return the survivors in model-input pixel space.
    """
    if tensor_meta.num_output_layers < 1:
        return []
    arr_addr = pyds.get_ptr(tensor_meta.out_buf_ptrs_host)
    if not arr_addr:
        return []
    void_arr = ctypes.cast(int(arr_addr), ctypes.POINTER(ctypes.c_void_p))
    layer_addr = void_arr[0]
    if not layer_addr:
        return []
    ptr = ctypes.cast(int(layer_addr), ctypes.POINTER(ctypes.c_float))

    # Stride decode + threshold filter in one pass.
    per_class = {}
    hand_dbg = []
    other_dbg = []
    n_anchors = len(_YOLOX_GRID)
    for i in range(n_anchors):
        base = i * 8
        obj = float(ptr[base + 4])
        if obj < 0.05:  # cheap pre-filter; full classes-per-anchor product is below threshold
            continue
        c0 = float(ptr[base + 5])
        c1 = float(ptr[base + 6])
        c2 = float(ptr[base + 7])
        # Pick the strongest class per anchor — same convention as YOLOX
        # canonical postprocessing.
        if c0 >= c1 and c0 >= c2:
            cls = 0; cls_score = c0
        elif c1 >= c2:
            cls = 1; cls_score = c1
        else:
            cls = 2; cls_score = c2
        score = obj * cls_score
        if score < HANDDET_SCORE_THRESHOLD and cls != HANDDET_HAND_CLASS_ID:
            continue
        gx, gy, stride = _YOLOX_GRID[i]
        cx = (float(ptr[base + 0]) + gx) * stride
        cy = (float(ptr[base + 1]) + gy) * stride
        w = math.exp(float(ptr[base + 2])) * stride
        h = math.exp(float(ptr[base + 3])) * stride
        x1 = cx - w * 0.5
        y1 = cy - h * 0.5
        x2 = cx + w * 0.5
        y2 = cy + h * 0.5
        if cls == HANDDET_HAND_CLASS_ID:
            if score > 0.05 and len(hand_dbg) < 6:
                hand_dbg.append((round(score, 3), int(x1), int(y1), int(x2), int(y2)))
            if score < HANDDET_SCORE_THRESHOLD:
                continue
        else:
            if score > 0.5 and len(other_dbg) < 2:
                other_dbg.append((cls, round(score, 3), int(x1), int(y1), int(x2), int(y2)))
        per_class.setdefault(cls, []).append((score, x1, y1, x2, y2))

    detections = _yolox_nms(per_class, HANDDET_NMS_IOU)

    # Throttled debug log so DEBUG-level traffic stays readable.
    global _last_yolox_log
    now = time.monotonic()
    if log_det.isEnabledFor(logging.DEBUG) and now - _last_yolox_log > 1.0:
        _last_yolox_log = now
        log_det.debug(
            "yolox-decode anchors_kept=%d nms_out=%d hands_dbg=%s other_dbg=%s",
            sum(len(v) for v in per_class.values()),
            len(detections),
            hand_dbg, other_dbg,
        )
    return detections


# Letterbox parameters baked at startup. YOLOX-Hand runs as a primary
# GIE on the full camera frame, and nvinfer with `maintain-aspect-ratio=1
# symmetric-padding=1` scales the image into the model square by the
# smaller of width/height, centering the result. We pre-compute the scale
# and the y/x padding offsets so the per-frame decode is a small handful
# of multiplies — no min/max per anchor.
_HANDDET_SCALE = min(HANDDET_INPUT_SIZE / WIDTH, HANDDET_INPUT_SIZE / HEIGHT)
_HANDDET_PAD_X = (HANDDET_INPUT_SIZE - WIDTH * _HANDDET_SCALE) / 2.0
_HANDDET_PAD_Y = (HANDDET_INPUT_SIZE - HEIGHT * _HANDDET_SCALE) / 2.0


def _handdet_src_pad_probe(pad, info, _user_data):
    """Inject one synthetic `Hand` NvDsObjectMeta per YOLOX hand detection.

    Runs on the YOLOX-Hand nvinfer element's SRC pad — *between* the
    detector (primary GIE on the full camera frame) and the landmark
    tertiary. Reads the [1, 2100, 8] tensor that YOLOX attached to
    `frame_meta.frame_user_meta_list`, decodes it via `_YOLOX_GRID`,
    keeps only `hand` class rows above HANDDET_SCORE_THRESHOLD, maps
    each surviving box from model-space (with letterbox padding) back
    to image space, and adds a synthetic NvDsObjectMeta to the frame.
    The downstream nvinfer (gie-id=4, operate-on-gie-id=3,
    operate-on-class-ids=2) then crops those hand boxes and runs
    landmark inference on each.
    """
    # Cheapest possible early-out when the overlay is off: skip the whole
    # tensor decode + object injection. With no synthetic Hand objects on
    # the frame the downstream landmark tertiary has nothing to operate
    # on and its TRT inference is skipped, so disabling the toggle truly
    # turns the tertiary cost off — not just its rendering.
    if not _hands_overlay_enabled:
        return Gst.PadProbeReturn.OK

    gst_buffer = info.get_buffer()
    if not gst_buffer:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    frame_list = batch_meta.frame_meta_list
    while frame_list is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)
        except StopIteration:
            break

        # Pull the YOLOX tensor off the frame's user-meta list. Primary
        # GIE attaches tensor meta at frame level (not on a parent obj
        # like secondary mode does), so we walk frame_user_meta_list.
        hands = []
        for user_meta in _iter_user_meta(frame_meta.frame_user_meta_list):
            if user_meta.base_meta.meta_type != _TENSOR_META_TYPE:
                continue
            tensor_meta = pyds.NvDsInferTensorMeta.cast(user_meta.user_meta_data)
            if tensor_meta.unique_id != HANDDET_GIE_ID:
                continue
            raw = _read_yolox_detections(tensor_meta)
            hands = sorted(
                (d for d in raw if d[0] == HANDDET_HAND_CLASS_ID),
                key=lambda d: -d[1],
            )[:HANDDET_MAX_PER_FRAME]
            break

        if not hands:
            try:
                frame_list = frame_list.next
            except StopIteration:
                break
            continue

        inv_scale = 1.0 / _HANDDET_SCALE
        for _cls, score, x1m, y1m, x2m, y2m in hands:
            # Letterbox un-pad → un-scale → image-space pixels.
            x1 = (x1m - _HANDDET_PAD_X) * inv_scale
            y1 = (y1m - _HANDDET_PAD_Y) * inv_scale
            x2 = (x2m - _HANDDET_PAD_X) * inv_scale
            y2 = (y2m - _HANDDET_PAD_Y) * inv_scale
            # Clip to frame; the letterbox math can push detections
            # outside when YOLOX hallucinates near the padding bands.
            x1 = max(0.0, min(WIDTH - 1.0,  x1))
            y1 = max(0.0, min(HEIGHT - 1.0, y1))
            x2 = max(0.0, min(WIDTH - 1.0,  x2))
            y2 = max(0.0, min(HEIGHT - 1.0, y2))
            bw = x2 - x1
            bh = y2 - y1
            if bw <= 1 or bh <= 1:
                continue
            child = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)
            child.unique_component_id = HANDDET_GIE_ID
            child.class_id = HANDDET_HAND_CLASS_ID
            child.object_id = _UNTRACKED_OBJECT_ID
            child.confidence = score
            child.detector_bbox_info.org_bbox_coords.left = int(x1)
            child.detector_bbox_info.org_bbox_coords.top = int(y1)
            child.detector_bbox_info.org_bbox_coords.width = int(bw)
            child.detector_bbox_info.org_bbox_coords.height = int(bh)
            rp = child.rect_params
            rp.left = x1
            rp.top = y1
            rp.width = bw
            rp.height = bh
            rp.has_bg_color = 0
            rp.border_width = 0
            child.obj_label = "Hand"
            # No parent — Hand is a primary-detected object now, not a
            # child of a PeopleNet Person. The landmark tertiary filters
            # by unique_component_id + class_id, not by parent linkage.
            pyds.nvds_add_obj_meta_to_frame(frame_meta, child, None)

        try:
            frame_list = frame_list.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


# ---------------------------------------------------------------------------
# MediaPipe Hand-Landmark tensor decode + skeleton draw
# ---------------------------------------------------------------------------

def _read_hand_keypoints(tensor_meta, rect_params):
    """Decode a MediaPipe Hand Landmark tensor blob into image-space keypoints.

    The landmark ONNX has three outputs (per inference batch):
      0. `xyz_x21`                  : float[63] — 21 keypoints x (x, y, z)
                                       with x/y in 0..HANDLM_INPUT_SIZE
                                       pixel space, z as relative depth.
      1. `hand_score`               : float    — sigmoid-style presence
                                       score [0, 1].
      2. `lefthand_0_or_righthand_1`: float    — 0 = left, 1 = right
                                       (sigmoid score; >0.5 = right).

    nvinfer doesn't guarantee a stable layer order across runs / engine
    rebuilds, so we look up each output by name (`NvDsInferLayerInfo.layerName`).
    Returns `None` if the layout is unrecognised or the presence score
    falls below HAND_PRESENCE_THRESHOLD (which means the YOLOX bbox was
    almost certainly a false positive — usually a face or a tightly
    clenched fist).
    """
    if tensor_meta.num_output_layers < 3:
        return None
    arr_addr = pyds.get_ptr(tensor_meta.out_buf_ptrs_host)
    if not arr_addr:
        return None
    void_arr = ctypes.cast(int(arr_addr), ctypes.POINTER(ctypes.c_void_p))

    xyz_ptr = None
    score_ptr = None
    handed_ptr = None
    for i in range(tensor_meta.num_output_layers):
        layer_addr = void_arr[i]
        if not layer_addr:
            continue
        try:
            layer_info = pyds.get_nvds_LayerInfo(tensor_meta, i)
            name = layer_info.layerName
        except Exception:
            name = ""
        fptr = ctypes.cast(int(layer_addr), ctypes.POINTER(ctypes.c_float))
        if name == "xyz_x21":
            xyz_ptr = fptr
        elif name == "hand_score":
            score_ptr = fptr
        elif name == "lefthand_0_or_righthand_1":
            handed_ptr = fptr
    if xyz_ptr is None or score_ptr is None:
        return None

    presence = float(score_ptr[0])
    if presence < HAND_PRESENCE_THRESHOLD:
        return None
    handedness = "right" if (handed_ptr is not None and float(handed_ptr[0]) >= 0.5) else "left"

    left, top = float(rect_params.left), float(rect_params.top)
    width, height = float(rect_params.width), float(rect_params.height)
    inv = 1.0 / float(HANDLM_INPUT_SIZE)

    keypoints = []
    for i in range(21):
        x_px = xyz_ptr[i * 3 + 0]
        y_px = xyz_ptr[i * 3 + 1]
        z_rel = xyz_ptr[i * 3 + 2]
        keypoints.append({
            "name": HAND_KEYPOINT_NAMES[i],
            "x": int(left + x_px * inv * width),
            "y": int(top + y_px * inv * height),
            "z": round(float(z_rel), 3),
        })
    return {
        "presence": round(presence, 3),
        "handedness": handedness,
        "keypoints": keypoints,
    }


def _draw_hand_skeleton(batch_meta, frame_meta, hand):
    """Paint a 21-keypoint hand skeleton via NvDsDisplayMeta.

    Each display_meta caps at 16 shapes per kind, and the canonical
    MediaPipe Hands topology has 21 dots + 21 edges. We therefore
    allocate two display metas back-to-back and split the keypoints /
    edges between them so the whole skeleton lands on the frame.

    Color is hue-coded by handedness (yellow for right, magenta for
    left) so the viewer can tell hands apart when both are in frame.
    """
    keypoints = hand["keypoints"]
    if hand["handedness"] == "right":
        color = (0.98, 0.85, 0.20, 1.0)  # warm yellow
    else:
        color = (0.95, 0.30, 0.85, 1.0)  # magenta

    def _emit(slice_range, edge_pairs):
        if not slice_range and not edge_pairs:
            return
        dm = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
        r, g, b, a = color
        # Joints
        n_circ = 0
        for idx in slice_range:
            if n_circ >= _DISPLAY_META_CAP:
                break
            kp = keypoints[idx]
            c = dm.circle_params[n_circ]
            c.xc, c.yc = _clamp_xy(kp["x"], kp["y"])
            c.radius = 4
            c.has_bg_color = 1
            c.circle_color.set(r, g, b, a)
            c.bg_color.set(r, g, b, a)
            n_circ += 1
        dm.num_circles = n_circ
        # Bones
        n_line = 0
        for a_idx, b_idx in edge_pairs:
            if n_line >= _DISPLAY_META_CAP:
                break
            a_kp = keypoints[a_idx]
            b_kp = keypoints[b_idx]
            ln = dm.line_params[n_line]
            ln.x1, ln.y1 = _clamp_xy(a_kp["x"], a_kp["y"])
            ln.x2, ln.y2 = _clamp_xy(b_kp["x"], b_kp["y"])
            ln.line_width = 2
            ln.line_color.set(r, g, b, a)
            n_line += 1
        dm.num_lines = n_line
        pyds.nvds_add_display_meta_to_frame(frame_meta, dm)

    # Split: first display_meta gets the wrist + first 15 finger joints
    # and the first 16 edges (the four-fingers' lower segments + thumb).
    # Second gets the remaining 5 finger tips and the 5 finger-tip edges
    # plus the palm-closure edge. Cleanly fits both 16-shape caps.
    _emit(range(0, 16), HAND_SKELETON_EDGES[:16])
    _emit(range(16, 21), HAND_SKELETON_EDGES[16:])


# ---------------------------------------------------------------------------
# Bbox padding probe: expand PeopleNet Person crops before MoveNet
# ---------------------------------------------------------------------------

def _peoplenet_src_pad_probe(pad, info, _user_data):
    """Pad each PeopleNet `Person` rect_params outward in place.

    Runs on the PeopleNet nvinfer SRC pad, *before* MoveNet's secondary
    GIE sink. Because nvinfer secondary mode crops from `obj.rect_params`
    on the frame, anything outside the tight body bbox is invisible to
    the pose model — wrists at the bbox edge end up looking like the
    "real" arm endpoints. Expanding the rect outward gives MoveNet
    enough margin to find keypoints on outstretched limbs.

    We mutate `rect_params` directly. nvdsosd later draws this same
    (now-wider) rectangle, so the visible box on the MJPEG stream
    matches what the secondary GIE actually saw — which is what we
    want for debugging "did the crop cover the limb?".
    """
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    frame_list = batch_meta.frame_meta_list
    while frame_list is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)
        except StopIteration:
            break

        obj_list = frame_meta.obj_meta_list
        while obj_list is not None:
            try:
                obj = pyds.NvDsObjectMeta.cast(obj_list.data)
            except StopIteration:
                break

            # Pad Person detections only — Face/Bag don't feed secondary
            # GIEs and would look weird if their boxes ballooned.
            if obj.unique_component_id == 1 and obj.class_id == 0:
                rp = obj.rect_params
                left, top = float(rp.left), float(rp.top)
                w, h = float(rp.width), float(rp.height)
                pad_w = w * PERSON_BBOX_PAD_X
                pad_h = h * PERSON_BBOX_PAD_Y
                new_left = max(0.0, left - pad_w)
                new_top = max(0.0, top - pad_h)
                new_right = min(float(WIDTH),  left + w + pad_w)
                new_bottom = min(float(HEIGHT), top + h + pad_h)
                rp.left = new_left
                rp.top = new_top
                rp.width = new_right - new_left
                rp.height = new_bottom - new_top

            try:
                obj_list = obj_list.next
            except StopIteration:
                break
        try:
            frame_list = frame_list.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


# ---------------------------------------------------------------------------
# Analytics zone geometry (parsed once at startup from the analytics config)
# ---------------------------------------------------------------------------

def _load_analytics_geometry():
    """Parse the analytics config and pull out drawable zones.

    The dashboard renders the ROIs as an SVG overlay on top of the live MJPEG
    (rather than letting nvdsanalytics paint them into the stream), so it
    needs to know the polygon coordinates. We read them once here; they don't
    change at runtime. Returns a dict shaped like:

        {
          "frame_width": 1280, "frame_height": 720,
          "rois": {"Center": {"polygon": [[400,180],[880,180], ...]}},
        }

    If the file is missing or malformed, we return safe defaults so the
    dashboard simply has nothing to draw.
    """
    geo = {"frame_width": WIDTH, "frame_height": HEIGHT, "rois": {}}
    cp = configparser.ConfigParser()
    try:
        if not cp.read(ANALYTICS_CONFIG):
            log.warning("analytics config not readable: %s", ANALYTICS_CONFIG)
            return geo
    except configparser.Error as e:
        log.warning("analytics config parse error: %s", e)
        return geo

    if cp.has_section("property"):
        try:
            geo["frame_width"] = int(cp.get("property", "config-width", fallback=str(WIDTH)))
            geo["frame_height"] = int(cp.get("property", "config-height", fallback=str(HEIGHT)))
        except ValueError:
            pass

    for section in cp.sections():
        if not section.startswith("roi-filtering-"):
            continue
        try:
            if not cp.getboolean(section, "enable", fallback=False):
                continue
        except ValueError:
            continue
        for key, val in cp.items(section):
            if not key.startswith("roi-") or key == "roi-rf":
                # roi-RF is the legacy uppercase name from nvidia's samples;
                # configparser lowercases keys, so it shows up as "roi-rf"
                # here. Skip anonymous filter rules and only pick up the
                # named "roi-<Name>" form that our config uses.
                continue
            name = key[len("roi-"):]
            try:
                nums = [int(n.strip()) for n in val.split(";") if n.strip()]
            except ValueError:
                continue
            if len(nums) < 6 or len(nums) % 2:
                continue
            polygon = [[nums[i], nums[i + 1]] for i in range(0, len(nums), 2)]
            # configparser stores keys lowercased, so "roi-Center" comes back
            # as "roi-center". Capitalize the first letter so the name in the
            # JSON matches what nvdsanalytics reports in its meta — which
            # uses the original casing from the config file.
            geo["rois"][name[:1].upper() + name[1:]] = {"polygon": polygon}
    return geo


_geometry = None  # populated at startup, before _start_pipeline()

# Module-level references to the GStreamer pipeline, GLib main loop, and bus.
# These are held here so they outlive `_start_pipeline()`'s frame — without
# strong refs, Python garbage-collects them once the function returns, which
# disposes the pipeline while it is still in the PLAYING state and tears the
# whole app down a second after Flask binds (symptom: `Empty reply from
# server` from /api/stats, systemd restart loop).
_pipeline = None
_loop = None
_bus = None
_loop_thread = None
# Throttle the per-frame YOLOX decode debug log so DEBUG mode doesn't
# write 30 lines a second into the journal. Module-level so the closure
# in `_read_yolox_post_detections` can mutate it via `global`.
_last_yolox_log = 0.0

# ---------------------------------------------------------------------------
# Pad probe: extract detection metadata from DeepStream batch buffer
# ---------------------------------------------------------------------------

def _iter_user_meta(user_meta_list):
    """Yield NvDsUserMeta entries from a user_meta_list, with safe iteration."""
    node = user_meta_list
    while node is not None:
        try:
            yield pyds.NvDsUserMeta.cast(node.data)
        except StopIteration:
            break
        try:
            node = node.next
        except StopIteration:
            break


def _osd_sink_pad_buffer_probe(pad, info, _user_data):
    """
    Runs on every buffer leaving the tracker+analytics chain (entering the OSD).
    Pulls NvDsBatchMeta, iterates each frame's:
      - object metadata (detections, tracker IDs, per-object analytics
        memberships: which ROI they're in, which line they crossed)
      - frame-level analytics metadata (cumulative line crossings, current
        ROI occupancy counts)
    and folds the results into shared state under _objects_lock.
    """
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    objects = []
    # All hands seen this frame, after landmark inference. Surfaced via
    # /api/stats so downstream tools can read finger coordinates without
    # having to scrape the rendered MJPEG.
    hands = []
    # (roi_name, tracker_id) tuples for objects currently inside an ROI on
    # this frame; used downstream to retire dwell timers for IDs that left.
    seen_in_roi = set()
    # Aggregated per-frame line crossing counts across all objects on this
    # frame (i.e. how many crossings nvdsanalytics flagged this frame).
    line_crossings_this_frame = collections.defaultdict(int)
    # Per-line cumulative counts as reported by nvdsanalytics on the frame
    # meta. We mirror these (rather than incrementing locally) because
    # nvdsanalytics is authoritative — it dedupes the same object crossing
    # the same line in the same frame.
    line_crossings_cum_snapshot = {}
    # Per-ROI occupancy snapshot from this frame's NvDsAnalyticsFrameMeta.
    # Used both to advertise configured ROI names from the first frame and
    # to surface current "people in zone" counts.
    roi_counts_snapshot = {}

    frame_list = batch_meta.frame_meta_list
    while frame_list is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)
        except StopIteration:
            break

        # --- per-object metadata -----------------------------------------
        obj_list = frame_meta.obj_meta_list
        while obj_list is not None:
            try:
                obj = pyds.NvDsObjectMeta.cast(obj_list.data)
            except StopIteration:
                break

            # Synthetic Hand objects (injected by _handdet_src_pad_probe).
            # They carry the MediaPipe Hand Landmark tensor in their
            # user_meta_list. Handle them separately from PeopleNet
            # detections so the analytics/tracker code below doesn't try
            # to dwell-time-track a wrist.
            if obj.unique_component_id == HANDDET_GIE_ID:
                hand_info = None
                for user_meta in _iter_user_meta(obj.obj_user_meta_list):
                    if user_meta.base_meta.meta_type != _TENSOR_META_TYPE:
                        continue
                    tensor_meta = pyds.NvDsInferTensorMeta.cast(
                        user_meta.user_meta_data
                    )
                    if tensor_meta.unique_id == HANDLM_GIE_ID:
                        hand_info = _read_hand_keypoints(
                            tensor_meta, obj.rect_params
                        )
                        break
                if hand_info is not None:
                    hands.append({
                        "box": [
                            int(obj.rect_params.left),
                            int(obj.rect_params.top),
                            int(obj.rect_params.width),
                            int(obj.rect_params.height),
                        ],
                        "score": round(float(obj.confidence), 3),
                        "handedness": hand_info["handedness"],
                        "presence": hand_info["presence"],
                        "keypoints": hand_info["keypoints"],
                    })
                    if _hands_overlay_enabled:
                        _draw_hand_skeleton(batch_meta, frame_meta, hand_info)
                # Suppress the OSD's auto-drawn box on hand children — the
                # keypoint skeleton is the visual we actually want.
                # text_params on a pool-allocated obj is zero-init so
                # nvdsosd skips text rendering for it automatically.
                obj.rect_params.border_width = 0
                try:
                    obj_list = obj_list.next
                except StopIteration:
                    break
                continue

            tracker_id = (
                int(obj.object_id)
                if obj.object_id != _UNTRACKED_OBJECT_ID else None
            )

            # Per-object meta. obj_user_meta_list holds analytics info (one
            # NvDsAnalyticsObjInfo describing line crossings + ROI membership
            # for this object on this frame) and, when pose is enabled, an
            # NvDsInferTensorMeta carrying MoveNet's raw [1,1,17,3] output.
            rois_for_obj = []
            lines_for_obj = []
            keypoints = None
            for user_meta in _iter_user_meta(obj.obj_user_meta_list):
                mt = user_meta.base_meta.meta_type
                if mt == _ANALYTICS_OBJ_META_TYPE:
                    anal = pyds.NvDsAnalyticsObjInfo.cast(user_meta.user_meta_data)
                    if anal.roiStatus:
                        rois_for_obj.extend(list(anal.roiStatus))
                    if anal.lcStatus:
                        lines_for_obj.extend(list(anal.lcStatus))
                elif mt == _TENSOR_META_TYPE:
                    tensor_meta = pyds.NvDsInferTensorMeta.cast(
                        user_meta.user_meta_data
                    )
                    # Filter on the secondary GIE's unique id so we don't try
                    # to interpret PeopleNet's detection tensors (if anyone
                    # ever flips output-tensor-meta on for it) as keypoints.
                    if tensor_meta.unique_id == MOVENET_GIE_ID:
                        keypoints = _read_movenet_keypoints(
                            tensor_meta, obj.rect_params
                        )

            if tracker_id is not None:
                for roi_name in rois_for_obj:
                    seen_in_roi.add((roi_name, tracker_id))
            for line_name in lines_for_obj:
                line_crossings_this_frame[line_name] += 1

            # Mutate the bounding-box border color so nvdsosd draws it in
            # blue when the object is inside any ROI and red otherwise. The
            # probe runs on nvdsosd's SINK pad, so changes here land before
            # the box is rendered. Components are 0..1 floats (R, G, B, A).
            if rois_for_obj:
                obj.rect_params.border_color.red = 0.2
                obj.rect_params.border_color.green = 0.5
                obj.rect_params.border_color.blue = 1.0
                obj.rect_params.border_color.alpha = 1.0
                obj.rect_params.border_width = 4
            else:
                obj.rect_params.border_color.red = 1.0
                obj.rect_params.border_color.green = 0.2
                obj.rect_params.border_color.blue = 0.2
                obj.rect_params.border_color.alpha = 1.0
                obj.rect_params.border_width = 3

            # Paint the skeleton directly onto the frame via nvdsosd. The
            # skeleton inherits the bbox border colour so the figure visually
            # belongs to its bounding box (red outside the ROI, blue inside).
            if _pose_overlay_enabled and keypoints:
                _draw_skeleton(
                    batch_meta,
                    frame_meta,
                    keypoints,
                    (
                        obj.rect_params.border_color.red,
                        obj.rect_params.border_color.green,
                        obj.rect_params.border_color.blue,
                        obj.rect_params.border_color.alpha,
                    ),
                )

            objects.append({
                "class_id": obj.class_id,
                "label": obj.obj_label,
                "confidence": round(float(obj.confidence), 3),
                "tracker_id": tracker_id,
                "box": [
                    int(obj.rect_params.left),
                    int(obj.rect_params.top),
                    int(obj.rect_params.width),
                    int(obj.rect_params.height),
                ],
                "rois": rois_for_obj,
                "crossed": lines_for_obj,
                # None when pose is disabled or MoveNet didn't emit a tensor
                # for this object; otherwise a list of 17 entries (each either
                # None for low-confidence keypoints, or a dict with name + x/y
                # in image pixel coords + confidence).
                "keypoints": keypoints,
            })

            try:
                obj_list = obj_list.next
            except StopIteration:
                break

        # --- frame-level analytics meta ----------------------------------
        # NvDsAnalyticsFrameMeta carries cumulative line-crossing counts
        # (objLCCumCnt), current per-frame line counts (objLCCurrCnt), per
        # ROI object id lists (objInROIcnt), and per-class total counts
        # (objCnt). We mirror the line and ROI numbers into _analytics on
        # each frame so the dashboard reflects nvdsanalytics' authoritative
        # numbers — and so configured ROI / line names show up in the JSON
        # even when empty.
        for user_meta in _iter_user_meta(frame_meta.frame_user_meta_list):
            if user_meta.base_meta.meta_type != _ANALYTICS_FRAME_META_TYPE:
                continue
            fanal = pyds.NvDsAnalyticsFrameMeta.cast(user_meta.user_meta_data)
            if fanal.objLCCumCnt:
                line_crossings_cum_snapshot.update(dict(fanal.objLCCumCnt))
            if fanal.objInROIcnt:
                # objInROIcnt is {roi_name: list_of_tracker_ids_in_roi};
                # take the length as the current occupancy count and just
                # register the name so empty zones still show up.
                for roi_name, ids in dict(fanal.objInROIcnt).items():
                    try:
                        count = len(ids)
                    except TypeError:
                        count = int(ids) if ids else 0
                    roi_counts_snapshot[roi_name] = count

        # Paint the configured ROI zones onto the frame. Same NvDsDisplayMeta
        # path as `_draw_skeleton`, same on/off pattern: the toggle here is
        # the `_zones_overlay_enabled` flag (flipped by /api/toggle/zones).
        # The label shows the cumulative entry count, sourced from analytics
        # state computed during the *previous* frame — one-frame lag that
        # nobody can see at 30 fps.
        if _zones_overlay_enabled and _geometry:
            for zone_name, info in _geometry.get("rois", {}).items():
                polygon = info.get("polygon")
                if not polygon:
                    continue
                count = _analytics["roi_total_entries"].get(zone_name, 0)
                _draw_zone(batch_meta, frame_meta, zone_name, polygon, count)

        try:
            frame_list = frame_list.next
        except StopIteration:
            break

    now = time.monotonic()

    with _objects_lock:
        _latest_objects.clear()
        _latest_objects.extend(objects)
        _latest_hands.clear()
        _latest_hands.extend(hands)

        _stats["total_detections"] += len(objects)
        for o in objects:
            if o["tracker_id"] is not None:
                if o["tracker_id"] not in _stats["active_track_ids"]:
                    _stats["total_unique_tracks"] += 1
                _stats["active_track_ids"].add(o["tracker_id"])

        # Line crossings: trust nvdsanalytics' cumulative counts when present,
        # fall back to our own per-frame increments otherwise (e.g. on
        # builds where objLCCumCnt isn't exposed).
        if line_crossings_cum_snapshot:
            for name, cum in line_crossings_cum_snapshot.items():
                _analytics["line_crossings_cum"][name] = int(cum)
        else:
            for name, n in line_crossings_this_frame.items():
                _analytics["line_crossings_cum"][name] += n
        _analytics["line_crossings_last_frame"] = dict(line_crossings_this_frame)

        # ROI occupancy: register every ROI nvdsanalytics knows about (so
        # configured zones show up even when empty) and snapshot current
        # counts.
        for name, count in roi_counts_snapshot.items():
            _analytics["roi_known"].add(name)
            _analytics["roi_current_count"][name] = int(count)

        # Dwell timers: any (roi, tid) seen now that wasn't tracked yet starts
        # a timer (and bumps the entry counter); any timer whose key isn't in
        # `seen_in_roi` retires into the completed deque.
        active = _analytics["roi_active_dwell"]
        for key in seen_in_roi:
            if key not in active:
                active[key] = now
                _analytics["roi_total_entries"][key[0]] += 1
        for key in list(active.keys()):
            if key in seen_in_roi:
                continue
            roi_name, tid = key
            duration = now - active.pop(key)
            _analytics["roi_completed_dwell"][roi_name].appendleft({
                "tracker_id": tid,
                "duration_seconds": round(duration, 2),
            })
            _analytics["roi_total_completed"][roi_name] += 1
            _analytics["roi_total_seconds"][roi_name] += duration
            if duration > _analytics["roi_max_seconds"][roi_name]:
                _analytics["roi_max_seconds"][roi_name] = duration

    return Gst.PadProbeReturn.OK


def _appsink_new_sample(sink):
    """Pull a pre-encoded JPEG buffer from the pipeline and stash its bytes."""
    global _latest_frame
    sample = sink.emit("pull-sample")
    if not sample:
        return Gst.FlowReturn.OK
    buf = sample.get_buffer()
    ok, mapinfo = buf.map(Gst.MapFlags.READ)
    if ok:
        jpeg = bytes(mapinfo.data)
        buf.unmap(mapinfo)
        with _frame_lock:
            _latest_frame = jpeg
            _stats["frame_count"] += 1
            _stats["last_frame_time"] = time.monotonic()
    return Gst.FlowReturn.OK


# ---------------------------------------------------------------------------
# Pipeline construction
# ---------------------------------------------------------------------------

def _build_pipeline():
    """
    The pipeline string. Uses software JPEG decode + software videoconvert
    on the input side for compatibility with arbitrary UVC cameras; switches
    to hardware (NVMM) memory through nvstreammux for the inference path.
    Built as a list + joined at the end so the optional secondary GIE
    (MoveNet pose) can be inserted with a plain `if`.
    """
    stages = [
        f"v4l2src device={DEVICE}",
        f"image/jpeg,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1",
        "jpegdec",
        "videoconvert",
        "video/x-raw,format=NV12",
        "nvvideoconvert",
        "video/x-raw(memory:NVMM),format=NV12",
        "mux.sink_0 "
        f"nvstreammux name=mux batch-size=1 width={WIDTH} height={HEIGHT} "
        f"batched-push-timeout=40000 live-source=1",
        f"nvinfer name=peoplenet config-file-path={INFER_CONFIG}",
        f"nvtracker ll-lib-file={TRACKER_LIB} ll-config-file={TRACKER_CONFIG} "
        f"tracker-width=640 tracker-height=384 gpu-id=0",
        # nvdsanalytics consumes the tracker IDs to evaluate line crossings,
        # ROI membership, direction filters, and overcrowding alerts defined
        # in its config file. Results are written into NvDsAnalyticsObjInfo
        # (per object) and NvDsAnalyticsFrameMeta (per frame) for the pad
        # probe to read.
        f"nvdsanalytics config-file={ANALYTICS_CONFIG}",
    ]
    if ENABLE_POSE:
        # MoveNet secondary GIE — runs per-person on the bbox crops from
        # PeopleNet and emits a [1,1,17,3] keypoint tensor for each crop.
        # `output-tensor-meta=1` in its config attaches the raw output to
        # each object's user_meta_list, where the pad probe reads it. Drop
        # this stage by setting ENABLE_POSE=0 in the systemd unit if the
        # extra inference cost is unwanted.
        stages.append(f"nvinfer config-file-path={MOVENET_CONFIG}")
    if ENABLE_HANDS:
        # YOLOX-Body-Head-Hand: SECOND PRIMARY GIE — process-mode=1 in
        # config_infer_handdet.txt — so it scans the full camera frame
        # rather than each PeopleNet Person crop. This decouples hand
        # detection from person detection: hands work for arms extended
        # past the body bbox, hands on a desk with no person framed,
        # and so on. Detection output ([1, 2100, 8]) attaches to
        # `frame_user_meta_list`; our src-pad probe decodes it (grid
        # decode + per-class NMS + letterbox un-padding) and injects
        # one synthetic NvDsObjectMeta per surviving `hand` row.
        # Naming the element so we can locate its src pad in
        # `_start_pipeline` and attach the inject probe.
        stages.append(
            f"nvinfer name=handdet config-file-path={HANDDET_CONFIG}"
        )
        # MediaPipe Hand Landmark tertiary GIE — operates on the
        # synthetic Hand objects injected by the probe above. Its
        # `output-tensor-meta=1` attaches the 21-keypoint xyz +
        # presence + handedness tensors to each Hand object's
        # user_meta_list, which the OSD probe reads to draw the
        # finger skeleton.
        stages.append(f"nvinfer config-file-path={HANDLM_CONFIG}")
    stages += [
        "nvvideoconvert",
        "nvdsosd display-bbox=1 display-text=1",
        # JPEG-encode with NVIDIA's hardware encoder, fed directly from NVMM
        # NV12 — nvjpegenc's sink template explicitly accepts that. This
        # avoids the prior software path (nvvideoconvert→system-I420→jpegenc),
        # which can't be made to work on Tegra: nvvideoconvert's default VIC
        # backend rejects RGB/BGR conversions ("RGB/BGR Format transformation
        # is not supported by VIC use GPU instead") and the GPU backend
        # (`compute-hw=1`) can't produce system-memory I420 from NVMM NV12
        # ("transform could not transform … format=NV12 … in anything we
        # support"). Encoding straight from NVMM with nvjpegenc sidesteps
        # both failures and is HW-accelerated.
        "nvjpegenc quality=85",
        "appsink name=sink emit-signals=true sync=false drop=true max-buffers=2",
    ]
    return " ! ".join(stages)


def _on_bus_message(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        log_gst.error("pipeline error: %s (debug: %s)", err, debug)
        loop.quit()
    elif t == Gst.MessageType.WARNING:
        warn, debug = message.parse_warning()
        log_gst.warning("pipeline warning: %s (debug: %s)", warn, debug)
    elif t == Gst.MessageType.EOS:
        log_gst.info("end-of-stream")
        loop.quit()


def _start_pipeline():
    global _pipeline, _loop, _bus, _loop_thread

    Gst.init(None)
    os.makedirs(ENGINE_DIR, exist_ok=True)

    pipeline_str = _build_pipeline()
    log.info("pipeline: %s", pipeline_str)
    pipeline = Gst.parse_launch(pipeline_str)
    if not pipeline:
        log.error("failed to parse pipeline")
        return

    # Wire appsink callback for MJPEG framegrab. We deliberately don't set a
    # `caps` property on the sink here: the pipeline already terminates in
    # `nvjpegenc`, so upstream caps will be `image/jpeg,...` and the appsink
    # accepts whatever flows in. Setting `caps=video/x-raw,format=BGR` here
    # (as the original implementation did, back when Flask re-encoded BGR
    # frames with cv2) makes the appsink reject the JPEG buffers and the
    # pipeline silently delivers zero samples.
    sink = pipeline.get_by_name("sink")
    sink.connect("new-sample", _appsink_new_sample)

    # Wire metadata probes by locating nvinfer elements by their `name`
    # property. Three probes get attached here:
    #   - PeopleNet src pad: expand Person bboxes so downstream secondary
    #     GIEs (MoveNet) see enough margin for outstretched limbs.
    #   - YOLOX-Hand src pad: decode hand detections + inject child
    #     NvDsObjectMeta for the landmark tertiary GIE to operate on.
    #   - nvdsosd sink pad: emit detection JSON + paint skeleton/zone
    #     display metas.
    osd = None
    peoplenet = None
    handdet = None
    it = pipeline.iterate_elements()
    while True:
        ret, e = it.next()
        if ret != Gst.IteratorResult.OK:
            break
        fn = e.get_factory().get_name()
        if fn == "nvdsosd":
            osd = e
        elif fn == "nvinfer":
            ename = e.get_property("name")
            if ename == "peoplenet":
                peoplenet = e
            elif ename == "handdet":
                handdet = e
    if osd:
        osd_sink_pad = osd.get_static_pad("sink")
        osd_sink_pad.add_probe(Gst.PadProbeType.BUFFER, _osd_sink_pad_buffer_probe, None)
    else:
        log_det.warning("could not locate nvdsosd element; detections won't be reported")
    if peoplenet:
        peoplenet_src_pad = peoplenet.get_static_pad("src")
        peoplenet_src_pad.add_probe(
            Gst.PadProbeType.BUFFER, _peoplenet_src_pad_probe, None
        )
    else:
        log_det.warning(
            "could not locate peoplenet nvinfer; pose secondary will crop "
            "to tight Person bbox and clip outstretched limbs"
        )
    if ENABLE_HANDS:
        if handdet:
            handdet_src_pad = handdet.get_static_pad("src")
            handdet_src_pad.add_probe(
                Gst.PadProbeType.BUFFER, _handdet_src_pad_probe, None
            )
        else:
            log_det.warning(
                "could not locate handdet nvinfer element; hand-landmark "
                "tertiary will have no objects to operate on"
            )

    # Bus loop on its own thread
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", _on_bus_message, loop)

    log.info("setting pipeline to PLAYING (first-boot FP16 engine build takes ~60s; subsequent starts use the cache)")
    pipeline.set_state(Gst.State.PLAYING)
    _stats["start_time"] = time.monotonic()

    # Promote the locals into module-level state so they survive this frame's
    # return. See the comment on _pipeline/_loop/_bus at the top of the file.
    _pipeline = pipeline
    _loop = loop
    _bus = bus
    _loop_thread = threading.Thread(target=loop.run, daemon=True)
    _loop_thread.start()


# ---------------------------------------------------------------------------
# Flask: MJPEG stream + JSON stats + tiny dashboard
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)


def _mjpeg_generator():
    last_emitted = None
    while True:
        with _frame_lock:
            jpeg = _latest_frame
        if jpeg is None or jpeg is last_emitted:
            # No frame yet, or no new frame since last yield — back off briefly
            # so we don't burn CPU spinning faster than the pipeline produces.
            time.sleep(0.01)
            continue
        last_emitted = jpeg
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
            + jpeg + b"\r\n"
        )


@flask_app.route("/stream")
def stream():
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@flask_app.route("/api/toggle/skeletons", methods=["POST"])
def toggle_skeletons():
    """Flip whether the pad probe paints the skeleton overlay on each frame.

    Plain global, GIL-protected — no lock needed for a single bool. The
    response echoes the new state so the dashboard can update its button
    label without waiting for the next /api/stats poll.
    """
    global _pose_overlay_enabled
    _pose_overlay_enabled = not _pose_overlay_enabled
    return jsonify({"overlay_enabled": _pose_overlay_enabled})


@flask_app.route("/api/toggle/zones", methods=["POST"])
def toggle_zones():
    """Same pattern as /api/toggle/skeletons but for the ROI zone overlay."""
    global _zones_overlay_enabled
    _zones_overlay_enabled = not _zones_overlay_enabled
    return jsonify({"overlay_enabled": _zones_overlay_enabled})


@flask_app.route("/api/toggle/hands", methods=["POST"])
def toggle_hands():
    """Same pattern as /api/toggle/skeletons but for the hand keypoint overlay."""
    global _hands_overlay_enabled
    _hands_overlay_enabled = not _hands_overlay_enabled
    return jsonify({"overlay_enabled": _hands_overlay_enabled})


@flask_app.route("/api/stats")
def api_stats():
    now = time.monotonic()
    with _objects_lock:
        objects = list(_latest_objects)
        hands_snapshot = list(_latest_hands)
        unique = _stats["total_unique_tracks"]
        total_dets = _stats["total_detections"]
        active_ids = sorted(_stats["active_track_ids"])

        # Snapshot the analytics state. We freeze cheaply by copying primitives;
        # the deques and dicts are small (DWELL_HISTORY_MAX = 50 per ROI).
        line_cum = dict(_analytics["line_crossings_cum"])
        line_last = dict(_analytics["line_crossings_last_frame"])
        known_rois = set(_analytics["roi_known"])
        current_counts = dict(_analytics["roi_current_count"])
        entry_counts = dict(_analytics["roi_total_entries"])
        active_dwell_items = list(_analytics["roi_active_dwell"].items())
        completed_by_roi = {
            roi: list(items)
            for roi, items in _analytics["roi_completed_dwell"].items()
        }
        completed_counts = dict(_analytics["roi_total_completed"])
        completed_totals = dict(_analytics["roi_total_seconds"])
        max_seconds = dict(_analytics["roi_max_seconds"])

    with _frame_lock:
        frames = _stats["frame_count"]
        start = _stats["start_time"]
        last = _stats["last_frame_time"]

    elapsed = now - start if start else 0
    fps = round(frames / elapsed, 1) if elapsed > 0 else 0.0

    # Group active dwells by ROI; include the live elapsed time per (roi, id).
    active_by_roi = collections.defaultdict(list)
    for (roi_name, tid), entered_at in active_dwell_items:
        active_by_roi[roi_name].append({
            "tracker_id": tid,
            "elapsed_seconds": round(now - entered_at, 2),
        })
    # Sort each ROI's active list by who's been there longest, descending.
    for v in active_by_roi.values():
        v.sort(key=lambda d: d["elapsed_seconds"], reverse=True)

    # Build the per-ROI summary block. Includes both active (live) and
    # completed (rolled-up) statistics. We seed the name set from `known_rois`
    # (every ROI nvdsanalytics has reported, even when empty) so the
    # dashboard lists configured zones from the first frame.
    roi_names = (
        known_rois
        | set(active_by_roi.keys())
        | set(completed_by_roi.keys())
        | set(completed_counts.keys())
    )
    rois = {}
    for name in sorted(roi_names):
        completed_n = completed_counts.get(name, 0)
        completed_total = completed_totals.get(name, 0.0)
        avg = round(completed_total / completed_n, 2) if completed_n else 0.0
        # Prefer nvdsanalytics' own per-frame count (`current_counts`) over
        # our tracker-ID-based one — the two should match, but the analytics
        # count is updated every frame, while the dwell-derived one only
        # changes when a tracker ID is seen/missed.
        current_count = current_counts.get(name, len(active_by_roi.get(name, [])))
        rois[name] = {
            "current": active_by_roi.get(name, []),
            "current_count": current_count,
            "total_entries": entry_counts.get(name, 0),
            "completed_count": completed_n,
            "avg_dwell_seconds": avg,
            "max_dwell_seconds": round(max_seconds.get(name, 0.0), 2),
            "recent_completed": completed_by_roi.get(name, []),
        }

    return jsonify({
        "timestamp": int(time.time()),
        "hostname": DEVICE_ID,
        "camera": {
            "device": DEVICE,
            "resolution": f"{WIDTH}x{HEIGHT}@{FRAMERATE}fps",
        },
        "pipeline": {
            "frames": frames,
            "fps": fps,
            "uptime_seconds": int(elapsed),
            "last_frame_ago": round(now - last, 2) if last else None,
        },
        "detector": {
            "model": "PeopleNet FP16 (ResNet34)",
            "total_detections": total_dets,
            "unique_tracks": unique,
            "active_track_count": len(active_ids),
        },
        "pose": {
            "model": "MoveNet single-pose Lightning",
            "overlay_enabled": _pose_overlay_enabled,
        },
        "hands": {
            "model": "YOLOX-BHH + MediaPipe Hand Landmark (21pt)",
            "overlay_enabled": _hands_overlay_enabled,
            "count": len(hands_snapshot),
            "detections": hands_snapshot,
        },
        "analytics": {
            "line_crossings": line_cum,
            "line_crossings_last_frame": line_last,
            "rois": rois,
            "zones_overlay_enabled": _zones_overlay_enabled,
            # Static zone geometry from analytics_config.txt — kept in the
            # JSON response for downstream tools that want to know the zone
            # shapes; the dashboard itself doesn't render zones any more
            # (nvdsosd paints them via NvDsDisplayMeta).
            "geometry": _geometry or {"frame_width": WIDTH, "frame_height": HEIGHT, "rois": {}},
        },
        "objects": objects,
    })


_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>NVIDIA DeepStream — Avocado</title>
<style>
  body { font-family: ui-monospace, "SF Mono", Menlo, monospace;
         background: #09090b; color: #fafafa; margin: 0; padding: 24px; }
  h1 { font-size: 18px; font-weight: 600; margin: 0 0 16px; }
  h1 span { color: #84cc16; }
  h3 { font-size: 11px; color: #71717a; text-transform: uppercase;
       margin: 16px 0 8px; letter-spacing: 0.05em; }
  .grid { display: grid; gap: 16px; max-width: 1200px; margin: 0 auto; }
  .card { background: #18181b; border: 1px solid #27272a;
          border-radius: 12px; padding: 16px; }
  .video-card img { width: 100%; display: block; border-radius: 8px; background: #000; }
  .video-wrap { line-height: 0; }
  .video-toolbar {
    display: flex; gap: 8px; justify-content: flex-end;
    margin-top: 10px; line-height: normal;
  }
  .btn {
    background: #27272a; color: #fafafa; border: 1px solid #3f3f46;
    padding: 6px 12px; border-radius: 6px; cursor: pointer;
    font: inherit; font-size: 12px;
  }
  .btn:hover { background: #3f3f46; }
  .btn.on  { background: #84cc16; color: #052e16; border-color: #84cc16; font-weight: 600; }
  .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
         gap: 12px; }
  .row.tight { gap: 8px; }
  .cell { padding: 8px 12px; background: #09090b; border-radius: 8px; }
  .cell-label { font-size: 10px; text-transform: uppercase; color: #71717a; }
  .cell-value { font-size: 20px; font-weight: 600; margin-top: 4px; }
  .cell-value.accent { color: #84cc16; }
  .cell-sub { font-size: 11px; color: #a1a1aa; margin-top: 2px; }
  .obj-row { padding: 6px 12px; font-size: 12px; border-bottom: 1px solid #27272a;
             display: flex; gap: 12px; align-items: center; }
  .obj-row:last-child { border-bottom: none; }
  .obj-label { font-weight: 600; min-width: 80px; }
  .obj-id { color: #84cc16; min-width: 60px; }
  .obj-conf { color: #a1a1aa; }
  .obj-tag { background: #27272a; color: #d4d4d8; font-size: 10px;
             padding: 2px 6px; border-radius: 4px; margin-left: 4px; }
  .obj-tag.accent { background: #84cc16; color: #052e16; font-weight: 700; }
  .roi-block { padding: 10px 12px; background: #09090b; border-radius: 8px;
               margin-bottom: 8px; }
  .roi-block:last-child { margin-bottom: 0; }
  .roi-head { display: flex; gap: 16px; align-items: baseline;
              border-bottom: 1px solid #27272a; padding-bottom: 6px;
              margin-bottom: 6px; }
  .roi-name { font-weight: 600; color: #84cc16; }
  .roi-stat { font-size: 11px; color: #a1a1aa; }
  .roi-stat strong { color: #fafafa; font-weight: 600; }
  .dwell-row { display: flex; gap: 12px; font-size: 12px;
               padding: 3px 0; color: #d4d4d8; }
  .dwell-id { color: #84cc16; min-width: 60px; }
  .dwell-time { font-variant-numeric: tabular-nums; min-width: 60px; }
  .empty { font-size: 11px; color: #52525b; padding: 6px 0; }
</style></head>
<body>
<div class="grid">
  <h1><span>avocado</span> nvidia deepstream &mdash; detection + tracking + pose + analytics</h1>
  <div class="card video-card">
    <div class="video-wrap">
      <img src="/stream" alt="Live feed">
    </div>
    <div class="video-toolbar">
      <button class="btn" id="toggle-zones">Show zones</button>
      <button class="btn" id="toggle-skeletons">Show skeletons</button>
      <button class="btn" id="toggle-hands">Show hands</button>
    </div>
  </div>
  <div class="card">
    <div class="row" id="cells"></div>
  </div>
  <div class="card">
    <h3>Zone entries</h3>
    <div class="row tight" id="entries"></div>
  </div>
  <div class="card">
    <h3>ROI dwell time</h3>
    <div id="rois"></div>
  </div>
  <div class="card">
    <h3>Live objects</h3>
    <div id="objs"></div>
  </div>
</div>
<script>
const fmtDuration = (s) => {
  if (s == null) return "—";
  if (s < 60) return s.toFixed(1) + "s";
  const m = Math.floor(s / 60); const r = s - m * 60;
  return m + "m " + r.toFixed(0) + "s";
};

// --- Overlay toggles -------------------------------------------------------
// Neither the skeleton nor the ROI rectangle is rendered client-side any
// more — `nvdsosd` paints both into the JPEG stream via NvDsDisplayMeta in
// the pad probe. Toggling either is a server-side flag flip; this UI layer
// just POSTs to the right endpoint and re-reads the resulting state from
// /api/stats on the next poll.
const zonesBtn = document.getElementById("toggle-zones");
const skeletonsBtn = document.getElementById("toggle-skeletons");
const handsBtn = document.getElementById("toggle-hands");

// Initial state gets overwritten by the first /api/stats poll.
let zonesEnabled = false;
let skeletonsEnabled = false;
let handsEnabled = false;

function applyButtonLabels() {
  zonesBtn.textContent = zonesEnabled ? "Hide zones" : "Show zones";
  zonesBtn.classList.toggle("on", zonesEnabled);
  skeletonsBtn.textContent = skeletonsEnabled ? "Hide skeletons" : "Show skeletons";
  skeletonsBtn.classList.toggle("on", skeletonsEnabled);
  handsBtn.textContent = handsEnabled ? "Hide hands" : "Show hands";
  handsBtn.classList.toggle("on", handsEnabled);
}

async function postToggle(path, expectedKey) {
  // Optimistic flip would race the user clicking twice; just trust the
  // server's response (it's the source of truth).
  try {
    const r = await fetch(path, { method: "POST" });
    const data = await r.json();
    return !!data[expectedKey];
  } catch (e) {
    return null;
  }
}

zonesBtn.addEventListener("click", async () => {
  const v = await postToggle("/api/toggle/zones", "overlay_enabled");
  if (v !== null) { zonesEnabled = v; applyButtonLabels(); }
});
skeletonsBtn.addEventListener("click", async () => {
  const v = await postToggle("/api/toggle/skeletons", "overlay_enabled");
  if (v !== null) { skeletonsEnabled = v; applyButtonLabels(); }
});
handsBtn.addEventListener("click", async () => {
  const v = await postToggle("/api/toggle/hands", "overlay_enabled");
  if (v !== null) { handsEnabled = v; applyButtonLabels(); }
});
applyButtonLabels();


async function poll() {
  try {
    const r = await fetch("/api/stats");
    const s = await r.json();
    const a = s.analytics || {line_crossings:{}, rois:{}};

    // Sync both toggle labels with what the server actually has enabled —
    // the pad probe owns whether each overlay is painted, and the dashboard
    // is just reading those flags.
    let dirty = false;
    if (s.pose && typeof s.pose.overlay_enabled === "boolean"
        && skeletonsEnabled !== s.pose.overlay_enabled) {
      skeletonsEnabled = s.pose.overlay_enabled; dirty = true;
    }
    if (typeof a.zones_overlay_enabled === "boolean"
        && zonesEnabled !== a.zones_overlay_enabled) {
      zonesEnabled = a.zones_overlay_enabled; dirty = true;
    }
    if (s.hands && typeof s.hands.overlay_enabled === "boolean"
        && handsEnabled !== s.hands.overlay_enabled) {
      handsEnabled = s.hands.overlay_enabled; dirty = true;
    }
    if (dirty) applyButtonLabels();

    document.getElementById("cells").innerHTML = [
      ["FPS", s.pipeline.fps],
      ["Frames", s.pipeline.frames.toLocaleString()],
      ["Detections", s.detector.total_detections.toLocaleString()],
      ["Active tracks", s.detector.active_track_count],
      ["Unique tracks", s.detector.unique_tracks],
      ["Hands", (s.hands && s.hands.count != null) ? s.hands.count : 0],
      ["Uptime", s.pipeline.uptime_seconds + "s"],
    ].map(([l, v]) =>
      '<div class="cell"><div class="cell-label">'+l+'</div><div class="cell-value">'+v+'</div></div>'
    ).join("");

    // Zone entries: big counter per ROI, ticks up each time a new tracker
    // ID enters the rectangle.
    const roiNames = Object.keys(a.rois || {}).sort();
    document.getElementById("entries").innerHTML = roiNames.length
      ? roiNames.map(name => {
          const r = a.rois[name];
          const sub = r.current_count > 0
            ? '<div class="cell-sub">'+r.current_count+' in zone now</div>'
            : "";
          return '<div class="cell">'+
                 '<div class="cell-label">'+name+'</div>'+
                 '<div class="cell-value accent">'+(r.total_entries || 0).toLocaleString()+'</div>'+
                 sub +
                 '</div>';
        }).join("")
      : '<div class="empty">No ROIs configured in analytics_config.txt</div>';

    // ROI dwell: per-region summary plus live elapsed times.
    document.getElementById("rois").innerHTML = roiNames.length
      ? roiNames.map(name => {
          const r = a.rois[name];
          const live = (r.current || []).map(c =>
            '<div class="dwell-row">'+
            '<span class="dwell-id">id '+c.tracker_id+'</span>'+
            '<span class="dwell-time">'+fmtDuration(c.elapsed_seconds)+'</span>'+
            '</div>'
          ).join("") || '<div class="empty">no one in zone</div>';
          return '<div class="roi-block">'+
            '<div class="roi-head">'+
              '<span class="roi-name">'+name+'</span>'+
              '<span class="roi-stat"><strong>'+r.current_count+'</strong> now</span>'+
              '<span class="roi-stat"><strong>'+r.total_entries+'</strong> entries</span>'+
              '<span class="roi-stat">avg <strong>'+fmtDuration(r.avg_dwell_seconds)+'</strong></span>'+
              '<span class="roi-stat">max <strong>'+fmtDuration(r.max_dwell_seconds)+'</strong></span>'+
            '</div>'+
            live +
            '</div>';
        }).join("")
      : '<div class="empty">No ROIs configured in analytics_config.txt</div>';

    document.getElementById("objs").innerHTML = s.objects.length
      ? s.objects.map(o => {
          const rois = (o.rois || []).map(n => '<span class="obj-tag accent">in '+n+'</span>').join("");
          return '<div class="obj-row">'+
            '<span class="obj-label">'+o.label+'</span>'+
            '<span class="obj-id">id '+(o.tracker_id ?? "—")+'</span>'+
            '<span class="obj-conf">'+(o.confidence*100).toFixed(0)+'%</span>'+
            rois +
            '</div>';
        }).join("")
      : '<div class="obj-row" style="color:#71717a">no objects in frame</div>';
  } catch(e) {}
  setTimeout(poll, 1000);
}
poll();
</script>
</body></html>"""


@flask_app.route("/")
def dashboard():
    return Response(_DASHBOARD, content_type="text/html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("app starting")
    log.info("device:       %s", DEVICE_ID)
    log.info("camera:       %s @ %dx%d %dfps", DEVICE, WIDTH, HEIGHT, FRAMERATE)
    log.info("infer config:     %s", INFER_CONFIG)
    log.info("tracker cfg:      %s", TRACKER_CONFIG)
    log.info("analytics cfg:    %s", ANALYTICS_CONFIG)
    log.info("pose secondary:   %s", MOVENET_CONFIG if ENABLE_POSE else "(disabled)")
    log.info("hand det:         %s", HANDDET_CONFIG if ENABLE_HANDS else "(disabled)")
    log.info("hand landmark:    %s", HANDLM_CONFIG if ENABLE_HANDS else "(disabled)")
    log.info("dashboard:        http://0.0.0.0:%d", PORT)

    _geometry = _load_analytics_geometry()
    log.info("analytics zones:  %s", sorted(_geometry["rois"].keys()) or "(none)")

    _start_pipeline()
    flask_app.run(host="0.0.0.0", port=PORT, threaded=True)
