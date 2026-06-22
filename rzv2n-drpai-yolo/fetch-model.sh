#!/usr/bin/env bash

# Fetches the YOLOv3 DRP-AI3-compiled model bundle for RZ/V2N.
#
# Two sources are stitched together:
#   1. Small bundle files (deploy.json, deploy.params, preprocess/*) ship
#      directly in renesas-rz/rzv_ai_sdk under R01_object_detection/exe_v2n/
#      and are pulled via raw github.com URLs.
#   2. The big TVM-compiled inference graph (deploy.so, several MB) is a
#      GitHub release asset attached to v6.00 of rzv_ai_sdk:
#        R01_object_detection_deploy_tvm_v2n-v251.so
#
# Output lands in app/overlay/usr/lib/rzv2n-drpai-yolo/model/yolov3/ —
# .gitignore'd so the binary blobs don't enter our repo.

set -euo pipefail

# Pinned upstream — bumping requires re-validating that the deploy.so still
# matches the RUHMI_TAG (libtvm_runtime.so version) in app-compile.sh.
SDK_TAG="v6.00"
SDK_REPO="renesas-rz/rzv_ai_sdk"
EXE_PATH="R01_object_detection/exe_v2n/yolov3_onnx"
DEPLOY_SO_NAME="R01_object_detection_deploy_tvm_v2n-v251.so"

DEST="app/overlay/usr/lib/rzv2n-drpai-yolo/model/yolov3"
RAW_BASE="https://raw.githubusercontent.com/${SDK_REPO}/${SDK_TAG}/${EXE_PATH}"
RELEASE_URL="https://github.com/${SDK_REPO}/releases/download/${SDK_TAG}/${DEPLOY_SO_NAME}"

echo "============================================"
echo "Fetching YOLOv3 DRP-AI3 model bundle for RZ/V2N"
echo "  source: ${SDK_REPO}@${SDK_TAG}"
echo "  dest:   ${DEST}"
echo "============================================"

mkdir -p "${DEST}/preprocess"

fetch() {
    local url="$1" out="$2"
    if [ -f "$out" ] && [ -s "$out" ]; then
        echo "  skip: $(basename "$out") (already present)"
        return
    fi
    echo "  fetch: $(basename "$out")"
    curl -fsSL "$url" -o "$out"
}

# Small bundle files (graph + params + DRP/AI-MAC descriptors)
fetch "${RAW_BASE}/deploy.json"   "${DEST}/deploy.json"
fetch "${RAW_BASE}/deploy.params" "${DEST}/deploy.params"

PREPROC_FILES=(
    addr_map.txt
    aimac_cmd.bin
    aimac_desc.bin
    aimac_param_cmd.bin
    aimac_param_desc.bin
    drp_config.mem
    drp_desc.bin
    drp_param.bin
    drp_param_info.txt
    weight.bin
)
for f in "${PREPROC_FILES[@]}"; do
    fetch "${RAW_BASE}/preprocess/${f}" "${DEST}/preprocess/${f}"
done

# Compiled inference graph (release asset)
fetch "${RELEASE_URL}" "${DEST}/deploy.so"

echo ""
echo "Bundle contents:"
ls -lh "${DEST}/" "${DEST}/preprocess/" 2>/dev/null

echo ""
echo "Done. The model bundle is at:"
echo "  ${DEST}/"
echo "Run 'avocado build' followed by 'avocado provision -r dev' to deploy."
