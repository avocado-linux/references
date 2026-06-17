#!/usr/bin/env bash
#
# Build-time prep for the vision-engines extension. Runs in the SDK container
# during `avocado build`. Stages the prebuilt TensorRT engines for the current
# build target from `prebuilt-engines/<target>/` into the extension overlay.
#
# A TensorRT engine is the compiled form of a model's ONNX, pinned to the
# GPU's compute capability + SM count + memory hierarchy + TRT/CUDA version.
# It is therefore target-specific — engines committed under
# `prebuilt-engines/jetson-orin-nano-devkit/` will not necessarily run on an
# AGX Orin and vice versa. Each Avocado build targets a single board, so this
# hook stages only `prebuilt-engines/$AVOCADO_TARGET/`; the resulting
# vision-engines extension always contains exactly the right engines for the
# image being built.
#
# Engines are loaded at runtime directly from the read-only extension at
# /usr/lib/nvidia-deepstream/engines/<model>/ (the nvinfer configs point
# there). There is deliberately NO on-device compile fallback and NO /var
# staging: on an immutable OS the engine is shipped, dm-verity-verified, and
# OTA-able as part of this extension. The consequence is a hard requirement —
# every supported target MUST have prebuilt engines committed here. To add a
# target, see "Regenerating engines" in getting_started.md.

set -euo pipefail

TARGET="${AVOCADO_TARGET:-jetson-orin-nano-devkit}"
ENGINE_SRC_BASE="prebuilt-engines/${TARGET}"
ENGINE_DST_BASE="vision-engines/overlay/usr/lib/nvidia-deepstream/engines"

echo "Staging prebuilt TensorRT engines for target: ${TARGET}"

if [ ! -d "$ENGINE_SRC_BASE" ]; then
  echo "ERROR: no prebuilt engines directory for target '${TARGET}' at" >&2
  echo "       ${ENGINE_SRC_BASE}/. This reference loads engines from the" >&2
  echo "       read-only extension; there is no on-device compile fallback." >&2
  echo "       Build engines on matching hardware and commit them under" >&2
  echo "       ${ENGINE_SRC_BASE}/<model>/ (see getting_started.md)." >&2
  exit 1
fi

staged=0
for model in peoplenet movenet handdet handlandmark; do
  src_dir="$ENGINE_SRC_BASE/$model"
  dst_dir="$ENGINE_DST_BASE/$model"
  if [ -d "$src_dir" ] && ls "$src_dir"/*.engine >/dev/null 2>&1; then
    mkdir -p "$dst_dir"
    cp -v "$src_dir"/*.engine "$dst_dir/"
    staged=$((staged + 1))
  else
    echo "ERROR: no engine for '${model}' under ${src_dir}/." >&2
    echo "       Every model needs a committed engine for this target." >&2
    exit 1
  fi
done

echo "Staged engines for ${staged} models."
