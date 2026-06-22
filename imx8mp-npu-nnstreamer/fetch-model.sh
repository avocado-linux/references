#!/usr/bin/env bash
#
# Fetch the representative-image set used to calibrate the INT8 quantization.
#
# We don't download a model: quantize-model.py builds MobileNetV2 from
# tf.keras (weights pulled by Keras at quantization time) and post-training-
# quantizes it. INT8 PTQ needs a small set of representative inputs to
# calibrate activation ranges -- a few dozen natural images is plenty for a
# demo. For a real deployment, replace these with images representative of
# your actual scene (lighting, framing, classes).
#
# Output: app/build/rep/*.jpg  (gitignored)

set -euo pipefail

COUNT="${1:-50}"
DEST="app/build/rep"

echo "============================================"
echo "Fetching ${COUNT} representative images for INT8 calibration"
echo "  dest: ${DEST}"
echo "============================================"

mkdir -p "$DEST"

for i in $(seq 1 "$COUNT"); do
    out="${DEST}/rep_$(printf '%03d' "$i").jpg"
    if [ -s "$out" ]; then
        echo "  skip: $(basename "$out")"
        continue
    fi
    # picsum.photos returns a real 224x224 photo; the seed makes it reproducible.
    if ! curl -fsSL "https://picsum.photos/seed/avocado${i}/224/224" -o "$out"; then
        echo "  WARN: could not fetch image ${i} (network?); continuing"
        rm -f "$out"
    fi
done

n=$(find "$DEST" -name '*.jpg' -size +0c | wc -l)
echo ""
echo "Got ${n} representative images in ${DEST}/"
if [ "$n" -lt 8 ]; then
    echo "WARNING: very few calibration images -- INT8 accuracy will suffer."
    echo "Drop your own .jpg files into ${DEST}/ and re-run 'avocado build'."
fi
echo "Next: avocado build   (runs the in-SDK quantizer via app-compile.sh)"
