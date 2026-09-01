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
# there). There is no on-device compile fallback and no /var staging: on an
# immutable OS the engine is shipped, dm-verity-verified, and OTA-able as
# part of this extension.
#
# When prebuilt engines are missing for the current target (e.g. first-time
# bring-up on new hardware), the build succeeds with a warning and produces
# an image WITHOUT engines. The vision-app service will fail to start on
# that image (nvinfer can't load a missing engine file), but you CAN still
# provision the device and SSH in to build engines with trtexec. Once built,
# scp them back to prebuilt-engines/<target>/<model>/, rebuild, and redeploy.
# See "Regenerating engines" in getting_started.md.

set -euo pipefail

TARGET="${AVOCADO_TARGET:-jetson-orin-nano-devkit}"
ENGINE_SRC_BASE="prebuilt-engines/${TARGET}"
ENGINE_DST_BASE="vision-engines/overlay/usr/lib/nvidia-deepstream/engines"

echo "Staging prebuilt TensorRT engines for target: ${TARGET}"

if [ ! -d "$ENGINE_SRC_BASE" ]; then
  echo "WARNING: no prebuilt engines directory for target '${TARGET}' at" >&2
  echo "         ${ENGINE_SRC_BASE}/." >&2
  echo "         The image will build but vision-app will NOT start until" >&2
  echo "         engines are built on-device and committed. See" >&2
  echo "         'Regenerating engines' in getting_started.md." >&2
  exit 0
fi

staged=0
missing=0
for model in peoplenet movenet handdet handlandmark; do
  src_dir="$ENGINE_SRC_BASE/$model"
  dst_dir="$ENGINE_DST_BASE/$model"
  if [ -d "$src_dir" ] && ls "$src_dir"/*.engine >/dev/null 2>&1; then
    mkdir -p "$dst_dir"
    cp -v "$src_dir"/*.engine "$dst_dir/"
    staged=$((staged + 1))
  else
    echo "WARNING: no engine for '${model}' under ${src_dir}/." >&2
    missing=$((missing + 1))
  fi
done

if [ "$missing" -gt 0 ]; then
  echo "WARNING: ${missing} model(s) missing engines. vision-app will not" >&2
  echo "         start until all 4 engines are present." >&2
fi

echo "Staged engines for ${staged} of 4 models."
