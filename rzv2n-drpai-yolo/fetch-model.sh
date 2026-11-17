#!/usr/bin/env bash

# Fetches the YOLOv3 DRP-AI3 model bundle for RZ/V2N, compiled by Renesas
# with RUHMI 2026-06 (the runtime lib-ruhmi ships on Avocado 2026).
#
# Two sources are stitched together:
#   1. The MERA2 plan, the subgraph descriptors and a reference input with
#      the compiler's expected outputs ship in renesas-rz/rzv_ai_sdk under
#      R01_object_detection/exe_v2n/yolov3_onnx/ (raw github.com URLs).
#   2. The compiled DRP-AI subgraph (deploy.so, ~180 MB) is a GitHub release
#      asset of rzv_ai_sdk v8.00:
#        R01_object_detection_deploy_ruhmi_2026-06_v2n.so
#
# Output lands in app/overlay/usr/lib/rzv2n-drpai-yolo/model/yolov3/ —
# .gitignore'd so the binary blobs don't enter our repo.

set -euo pipefail

# Pinned upstream — bumping requires re-validating that the model still
# matches RUHMI_TAG in app-compile.sh and the lib-ruhmi runtime in the feed.
SDK_TAG="v8.00"
SDK_REPO="renesas-rz/rzv_ai_sdk"
EXE_PATH="R01_object_detection/exe_v2n/yolov3_onnx"
DEPLOY_SO_NAME="R01_object_detection_deploy_ruhmi_2026-06_v2n.so"
SUBGRAPH="sub_0000__CPU_DRP_TVM"

DEST="app/overlay/usr/lib/rzv2n-drpai-yolo/model/yolov3"
RAW_BASE="https://raw.githubusercontent.com/${SDK_REPO}/${SDK_TAG}/${EXE_PATH}"
RELEASE_URL="https://github.com/${SDK_REPO}/releases/download/${SDK_TAG}/${DEPLOY_SO_NAME}"

echo "============================================"
echo "Fetching YOLOv3 DRP-AI3 model bundle for RZ/V2N"
echo "  source: ${SDK_REPO}@${SDK_TAG}"
echo "  dest:   ${DEST}"
echo "============================================"

mkdir -p "${DEST}/${SUBGRAPH}" "${DEST}/interpreter_out"

fetch() {
    local url="$1" out="$2"
    if [ -f "$out" ] && [ -s "$out" ]; then
        echo "  skip: ${out#"${DEST}"/} (already present)"
        return
    fi
    echo "  fetch: ${out#"${DEST}"/}"
    curl -fsSL "$url" -o "$out.part"
    mv "$out.part" "$out"
}

# MERA2 plan + subgraph metadata
for f in mera.plan model_subgraphs.json project.mdp \
         "${SUBGRAPH}/deploy.json" "${SUBGRAPH}/deploy.params"; do
    fetch "${RAW_BASE}/${f}" "${DEST}/${f}"
done

# Reference input and the compiler's expected outputs, used by
# `rzv2n-drpai-yolo --selftest` to check the accelerator's results.
for f in interpreter_out/input_0.bin interpreter_out/ref_result_0_fp16.bin \
         interpreter_out/ref_result_1_fp16.bin interpreter_out/ref_result_2_fp16.bin; do
    fetch "${RAW_BASE}/${f}" "${DEST}/${f}"
done

# Compiled DRP-AI subgraph (release asset)
fetch "${RELEASE_URL}" "${DEST}/${SUBGRAPH}/deploy.so"

echo ""
echo "Bundle contents:"
ls -lhR "${DEST}/"

echo ""
echo "Done. The model bundle is at:"
echo "  ${DEST}/"
