#!/usr/bin/env bash
#
# Fetch the MoveNet SinglePose Lightning float SavedModel (we quantize it
# ourselves in app-compile.sh) plus a small representative-image set for INT8
# calibration.
#
# Outputs (gitignored):
#   app/build/movenet/   -- SavedModel (saved_model.pb + variables/)
#   app/build/rep/*.jpg  -- calibration images
#
# For real accuracy, replace the calibration images with frames representative
# of your scene -- ideally people in poses/lighting like your deployment.

set -euo pipefail

MODEL_DIR="app/build/movenet"
REP_DIR="app/build/rep"
COUNT="${1:-40}"
MOVENET_URL="https://tfhub.dev/google/movenet/singlepose/lightning/4?tf-hub-format=compressed"

echo "============================================"
echo "Fetching MoveNet SinglePose Lightning SavedModel + ${COUNT} calibration images"
echo "============================================"

if [ ! -f "$MODEL_DIR/saved_model.pb" ]; then
    mkdir -p "$MODEL_DIR"
    echo "Downloading MoveNet SavedModel..."
    curl -fsSL "$MOVENET_URL" -o /tmp/movenet.tar.gz
    tar -xzf /tmp/movenet.tar.gz -C "$MODEL_DIR"
    rm -f /tmp/movenet.tar.gz
    echo "  -> $MODEL_DIR"
else
    echo "MoveNet SavedModel already present in $MODEL_DIR"
fi

mkdir -p "$REP_DIR"
for i in $(seq 1 "$COUNT"); do
    out="${REP_DIR}/rep_$(printf '%03d' "$i").jpg"
    [ -s "$out" ] && continue
    if ! curl -fsSL "https://picsum.photos/seed/pose${i}/640/640" -o "$out"; then
        echo "  WARN: could not fetch image ${i} (network?); continuing"
        rm -f "$out"
    fi
done

n=$(find "$REP_DIR" -name '*.jpg' -size +0c | wc -l)
echo ""
echo "Got SavedModel + ${n} calibration images."
echo "NOTE: picsum images are generic. For best pose accuracy, drop real people"
echo "      frames (*.jpg) into ${REP_DIR}/ and re-run 'avocado build'."
echo "Next: avocado build   (quantizes MoveNet -> INT8 in the SDK)"
