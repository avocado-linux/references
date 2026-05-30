#!/usr/bin/env bash
#
# Build-time prep for the nvidia-deepstream reference. Runs in the SDK
# container during `avocado build`. Five jobs:
#
#   1. Download PeopleNet (~25 MB) from NGC into the model dir.
#   2. Download MoveNet single-pose Lightning (~9 MB) from PINTO's
#      pre-converted ONNX zoo for the secondary skeleton inference, and
#      rewrite its input layer from NHWC to NCHW so DS 7.1's nvinfer can
#      consume it without choking on the channel-dimension check.
#   3. Download YOLOX-Body-Head-Hand (~4 MB) — a single-stage detector
#      whose `hand` class drives the optional finger-tracking pipeline.
#   4. Download MediaPipe Hand Landmark (~11 MB), the 21-keypoint
#      regressor that runs as a tertiary GIE on each hand crop.
#   5. Stage pre-built TensorRT engines for the current build target
#      from `prebuilt-engines/<target>/`, if present. Skips the ~12 min
#      first-boot nvinfer compile when the target's engines have been
#      built ahead of time (TRT engines are pinned to GPU arch and
#      TRT/CUDA version, so they're per-target).
#
# All model artifacts (ONNXes + pre-built engines if any) are staged into
# app/overlay/usr/lib/nvidia-deepstream/models/ and then copied into the
# extension sysroot by app-install.sh. Python runtime dependencies
# (Flask, PyGObject) come from the Avocado package feed via avocado.yaml
# — no pip step needed.

set -euo pipefail

echo "[1/4] Downloading PeopleNet model from NGC..."
PEOPLENET_DIR="app/overlay/usr/lib/nvidia-deepstream/models/peoplenet"
mkdir -p "$PEOPLENET_DIR"

# PeopleNet pruned_quantized_decrypted_v2.3.4 — ONNX has Q/DQ nodes baked
# in, but TensorRT will build it as FP16 when network-mode=2 (the cluster
# nodes get folded back during optimization). This is NVIDIA's canonical
# PeopleNet ONNX URL.
NGC_BASE="https://api.ngc.nvidia.com/v2/models/org/nvidia/team/tao/peoplenet/pruned_quantized_decrypted_v2.3.4/files"

download() {
  local DIR=$1
  local URL=$2
  local FILE=$3
  local OUT="$DIR/$FILE"
  if [ -f "$OUT" ]; then
    echo "  cached: $FILE"
    return
  fi
  echo "  fetching: $FILE"
  curl -fsSL "$URL" -o "$OUT"
}

download "$PEOPLENET_DIR" "$NGC_BASE?redirect=true&path=resnet34_peoplenet_int8.onnx" resnet34_peoplenet_int8.onnx
download "$PEOPLENET_DIR" "$NGC_BASE?redirect=true&path=labels.txt" labels.txt
# Note: the int8 calibration cache (resnet34_peoplenet_int8.txt) is NOT
# downloaded because this reference runs PeopleNet in FP16 mode for a
# faster first-boot engine build. Add the .txt file and flip the nvinfer
# config to network-mode=1 if you want to switch to INT8.

echo "[2/4] Downloading MoveNet single-pose Lightning..."
MOVENET_DIR="app/overlay/usr/lib/nvidia-deepstream/models/movenet"
MOVENET_ONNX="$MOVENET_DIR/movenet_singlepose_lightning.onnx"
mkdir -p "$MOVENET_DIR"
if [ -f "$MOVENET_ONNX" ]; then
  echo "  cached: movenet_singlepose_lightning.onnx"
else
  # PINTO_model_zoo hosts the tf2onnx-converted MoveNet (Google TF Hub
  # source) as a tarball on Wasabi. The tarball is large (~72 MB) because
  # it bundles TFLite / OpenVINO / TFJS variants alongside the ONNX; we
  # extract only the ONNX (~9 MB) and ship that.
  echo "  fetching: PINTO MoveNet tarball (~72 MB; extracting ONNX only)"
  TMP=$(mktemp -d)
  trap "rm -rf $TMP" EXIT
  curl -fsSL "https://s3.ap-northeast-2.wasabisys.com/pinto-model-zoo/115_MoveNet/lightning_v4/resources.tar.gz" -o "$TMP/movenet.tar.gz"
  tar -xzf "$TMP/movenet.tar.gz" -C "$TMP" saved_model/model_float32.onnx

  # The shipped ONNX has an NHWC input ([1, 192, 192, 3]). nvinfer's
  # preprocessing in DS 7.1 hard-codes the channel dim at axis 1 (NCHW)
  # — `network-input-order=1` flips the inference shape but doesn't move
  # the channel check, so it still complains "RGB/BGR input format
  # specified but network input channels is not 3" and refuses to build
  # the engine. Splice a Transpose at the front of the graph so the model
  # exposes a standard NCHW input ([1, 3, 192, 192]). nvinfer never sees
  # the NHWC layout; everything else in the graph stays untouched.
  uv pip install --target "$TMP/onnx-deps" --python "$(which python3)" onnx >/dev/null
  PYTHONPATH="$TMP/onnx-deps" python3 - "$TMP/saved_model/model_float32.onnx" "$MOVENET_ONNX" <<'PYEOF'
import sys
import onnx
from onnx import helper, TensorProto

src_path, dst_path = sys.argv[1], sys.argv[2]
m = onnx.load(src_path)

orig = m.graph.input[0]
nhwc_name = orig.name + "_nhwc"
nchw_name = "input_0"

# Rename the existing input from a producer's perspective: every node that
# referenced it must now point at the post-Transpose tensor.
old_name = orig.name
for node in m.graph.node:
    for i, inp in enumerate(node.input):
        if inp == old_name:
            node.input[i] = nhwc_name

# Replace the graph input with a new NCHW entry.
new_input = helper.make_tensor_value_info(
    nchw_name, TensorProto.FLOAT, [1, 3, 192, 192]
)
m.graph.input.remove(orig)
m.graph.input.insert(0, new_input)

# Transpose: NCHW (input_0) -> NHWC (<old>_nhwc), perm=[0, 2, 3, 1].
m.graph.node.insert(0, helper.make_node(
    "Transpose",
    inputs=[nchw_name],
    outputs=[nhwc_name],
    perm=[0, 2, 3, 1],
    name="input_nchw_to_nhwc",
))

onnx.checker.check_model(m)
onnx.save(m, dst_path)
print("rewrote input from NHWC to NCHW via Transpose")
PYEOF
fi

echo "[3/4] Downloading YOLOX-Body-Head-Hand (320x320, non-post variant)..."
HANDDET_DIR="app/overlay/usr/lib/nvidia-deepstream/models/handdet"
HANDDET_ONNX="$HANDDET_DIR/yolox_n_body_head_hand_320x320.onnx"
mkdir -p "$HANDDET_DIR"
if [ -f "$HANDDET_ONNX" ]; then
  echo "  cached: $(basename "$HANDDET_ONNX")"
else
  # PINTO YOLOX-BHH (nano) tarball is ~240 MB because it ships every
  # input-resolution variant (and the with/without-post-NMS pair for each).
  # We use the non-post 320x320 build whose output is a fixed-shape
  # [1, 2100, 8] tensor: 2100 anchors x (cx, cy, w, h, obj, c0, c1, c2).
  # We do grid decode + NMS in app.py. Why not the `_post_` build? It bakes
  # in a `NonMaxSuppression` op with a dynamic `[N, 7]` output, and
  # nvinfer/TRT in DS 7.1 doesn't expose an output optimization profile —
  # the engine ends up with N=1, so only the single top-scoring detection
  # per frame reaches us (always body, never hands). Fixed-shape output
  # sidesteps that.
  echo "  fetching: PINTO YOLOX-BHH tarball (~240 MB; extracting one ONNX)"
  TMPYX=$(mktemp -d)
  trap "rm -rf $TMPYX" EXIT
  curl -fsSL "https://s3.ap-northeast-2.wasabisys.com/pinto-model-zoo/426_YOLOX-Body-Head-Hand/resources_n.tar.gz" -o "$TMPYX/yolox.tar.gz"
  tar -xzf "$TMPYX/yolox.tar.gz" -C "$TMPYX" "yolox_n_body_head_hand_0461_0.4428_1x3x320x320.onnx"
  mv "$TMPYX/yolox_n_body_head_hand_0461_0.4428_1x3x320x320.onnx" "$HANDDET_ONNX"
fi

echo "[4/4] Downloading MediaPipe Hand Landmark (PINTO0309/hand_landmark v1.0.0)..."
HANDLM_DIR="app/overlay/usr/lib/nvidia-deepstream/models/handlandmark"
HANDLM_ONNX="$HANDLM_DIR/hand_landmark_sparse_224x224.onnx"
mkdir -p "$HANDLM_DIR"
if [ -f "$HANDLM_ONNX" ]; then
  echo "  cached: $(basename "$HANDLM_ONNX")"
else
  # The shipped ONNX has a dynamic batch dim (N), which TensorRT will let
  # us pin at engine build via nvinfer's batch-size=1. No transpose or
  # rewrite needed — input is already NCHW [N, 3, 224, 224]. Outputs are:
  #   xyz_x21         : [N, 63]  21 keypoints x (x, y, z) in input-pixel
  #                              coords (0..224 for x/y; z is relative depth)
  #   hand_score      : [N,  1]  presence/confidence
  #   lefthand_0_or_righthand_1 : [N, 1] handedness
  echo "  fetching: hand_landmark_sparse_Nx3x224x224.onnx (~11 MB)"
  curl -fsSL "https://github.com/PINTO0309/hand_landmark/releases/download/1.0.0/hand_landmark_sparse_Nx3x224x224.onnx" -o "$HANDLM_ONNX"
fi

echo "[5/5] Staging pre-built TensorRT engines for target ($AVOCADO_TARGET)..."
# Engines built on the matching Orin Nano / AGX Orin hardware, committed to
# the repo at `prebuilt-engines/<target>/<model>/`. Shipping them in the
# sysext alongside the ONNX skips the ~12 min first-boot TRT compile.
#
# TRT engines are pinned to GPU arch + TRT/CUDA version, so per-target
# directories. If a target has no pre-built engines, nvinfer compiles
# from the ONNX on first boot (the original behavior). Used to support
# both jetson-orin-nano-devkit and jetson-agx-orin-devkit; right now only
# the Nano directory is populated (the AGX engines need to be built on
# actual AGX hardware and committed separately).
ENGINE_SRC_BASE="prebuilt-engines/${AVOCADO_TARGET:-jetson-orin-nano-devkit}"
if [ -d "$ENGINE_SRC_BASE" ]; then
  for model in peoplenet movenet handdet handlandmark; do
    src_dir="$ENGINE_SRC_BASE/$model"
    dst_dir="app/overlay/usr/lib/nvidia-deepstream/models/$model"
    if [ -d "$src_dir" ] && ls "$src_dir"/*.engine >/dev/null 2>&1; then
      cp -v "$src_dir"/*.engine "$dst_dir/"
    else
      echo "  no pre-built engine for $model — nvinfer will compile from ONNX on first boot"
    fi
  done
else
  echo "  no pre-built engines for target ${AVOCADO_TARGET:-jetson-orin-nano-devkit} — nvinfer will compile from ONNX on first boot"
fi

echo "Model files:"
ls -lh "$PEOPLENET_DIR" "$MOVENET_DIR" "$HANDDET_DIR" "$HANDLM_DIR"

echo "Done."
