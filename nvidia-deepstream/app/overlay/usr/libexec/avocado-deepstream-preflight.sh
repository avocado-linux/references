#!/bin/sh
#
# Pre-start workarounds for nvidia-deepstream on Avocado OS.
#
# Avocado is an immutable OS: only /var is writable at runtime. This script
# only ever writes to /var (persistent across OTA) or /run (tmpfs, gone at
# reboot). It never overlays, bind-mounts, or otherwise touches /usr, /etc,
# or /opt — those paths are managed exclusively by the sysext/confext A/B
# mechanism and any in-place modification will break `avocado runtime deploy`
# (systemd-sysext's unmerge bails on "Read-only file system" if anything is
# mounted onto the path it needs to walk).
#
# Two preparations are needed before the python app builds its GStreamer
# pipeline:
#
# 1. Curate a GStreamer plugin scan directory that excludes
#    libcustom2d_preprocess.so.
#
#    The deepstream-7.1 package installs a helper library at
#    /usr/lib/gstreamer-1.0/deepstream/libcustom2d_preprocess.so. It is not
#    a GStreamer plugin (it's used by nvdspreprocess, which this reference
#    doesn't use), but the plugin scanner subprocess loads every .so in
#    that directory. Its dlopen-time constructors trigger
#    `pthread_setspecific: Invalid argument` inside glib; the scanner
#    aborts and on its synchronous-load recovery path the parent blacklists
#    the *next* file in alphabetical order — libgstnvvideoconvert.so. The
#    symptom is `gst_parse_error: no element "nvvideoconvert"`.
#
#    We build a directory under /run with symlinks to every real plugin
#    EXCEPT libcustom2d_preprocess.so, and point GST_PLUGIN_SYSTEM_PATH_1_0
#    at it from app.service. GStreamer scans only that directory, so the
#    bad library is never opened.
#
# 2. Stage every ONNX + pre-built TensorRT engine into /var so nvinfer's
#    engine caches are OTA-persistent.
#
#    nvinfer in DS 7.1 + TRT 10.x ignores model-engine-file for the *write*
#    path — it saves the freshly built engine next to onnx-file regardless.
#    Staging each ONNX from the sysext-shipped /usr/lib/.../models/<name>/
#    location into /var/lib/.../models/<name>/ means the engine lands next
#    to it on /var, where it survives sysext A/B swaps.
#
#    If the sysext also ships a pre-built `.engine` (committed under
#    `prebuilt-engines/<target>/<name>/` in the repo and staged into the
#    sysext during `app-compile.sh`), we stage that too so nvinfer loads
#    it instead of recompiling from the ONNX on first boot. The engine is
#    staged with the same size-compare semantics as the ONNX, so an OTA
#    that ships a newer engine (e.g. after a JetPack bump) overwrites
#    the cached /var copy on next boot — the engine doesn't only live
#    in /var. PeopleNet (primary GIE), MoveNet (secondary pose GIE),
#    YOLOX-Hand (secondary hand detector), and MediaPipe Hand Landmark
#    (tertiary GIE) all go through this path.

set -eu

# --- 1. Curated GStreamer plugin scan directory --------------------------------

GST_DIR=/run/avocado-gst-plugins
mkdir -p "${GST_DIR}"

# Clean any stale entries from a previous start in the same boot. /run is
# tmpfs so this is just a no-op on the first start.
find "${GST_DIR}" -maxdepth 1 -type l -delete 2>/dev/null || true

# Mirror every top-level GStreamer plugin.
for f in /usr/lib/gstreamer-1.0/*.so; do
  [ -e "$f" ] || continue
  ln -sf "$f" "${GST_DIR}/$(basename "$f")"
done

# Mirror every DeepStream plugin EXCEPT libcustom2d_preprocess.so.
for f in /usr/lib/gstreamer-1.0/deepstream/*.so; do
  [ -e "$f" ] || continue
  name=$(basename "$f")
  case "$name" in
    libcustom2d_preprocess.so) continue ;;
  esac
  ln -sf "$f" "${GST_DIR}/${name}"
done

# --- 2. Stage ONNX models into /var/lib ---------------------------------------
#
# Same logic for every model: copy the read-only sysext-shipped ONNX into the
# writable, OTA-persistent /var/lib path so nvinfer's auto-saved engine cache
# lives next to it on /var (where it survives sysext A/B swaps). If an OTA
# ships a newer ONNX, we detect via mtime and refresh — wiping the stale
# engine cache so nvinfer rebuilds.

# Compare two files by size — sysext-shipped files all bear a `Jan 1 1970`
# mtime from Avocado's deterministic build, so any prior copy in /var
# (with a real mtime) always wins an `-nt` check and we'd never refresh
# after a deploy that legitimately changes the file. Size mismatch is a
# cheap, good-enough proxy: byte-identical files almost certainly have
# identical contents, and any non-trivial change bumps the size.
size_differs() {
  local SRC=$1 DST=$2
  local SRC_SIZE DST_SIZE
  SRC_SIZE=$(stat -c %s "${SRC}" 2>/dev/null || echo 0)
  DST_SIZE=$(stat -c %s "${DST}" 2>/dev/null || echo 0)
  [ "${SRC_SIZE}" != "${DST_SIZE}" ]
}

stage_model() {
  local NAME=$1
  local ONNX=$2
  local SRC_DIR=/usr/lib/nvidia-deepstream/models/${NAME}
  local DST_DIR=/var/lib/nvidia-deepstream/models/${NAME}
  local SRC_ONNX=${SRC_DIR}/${ONNX}
  local DST_ONNX=${DST_DIR}/${ONNX}

  mkdir -p "${DST_DIR}"

  local ONNX_CHANGED=0
  if [ ! -f "${DST_ONNX}" ] || size_differs "${SRC_ONNX}" "${DST_ONNX}"; then
    cp "${SRC_ONNX}" "${DST_ONNX}"
    ONNX_CHANGED=1
  fi

  # Stage a pre-built engine if the sysext ships one. Two cases:
  #
  #   (a) sysext has an engine and our /var copy differs in size → OTA
  #       bump, overwrite the cached /var engine so nvinfer loads the
  #       new one on this start. Common after a deploy that ships an
  #       updated `.engine` (e.g. JetPack version bump invalidates the
  #       old engine).
  #
  #   (b) sysext has no engine but ONNX changed → wipe the stale cached
  #       engine so nvinfer recompiles from the new ONNX. Old behavior.
  #
  # If neither (a) nor (b) applies, leave the cached engine alone.
  local SHIPPED_ENGINE
  SHIPPED_ENGINE=$(ls "${SRC_DIR}"/*.engine 2>/dev/null | head -n 1)
  if [ -n "${SHIPPED_ENGINE}" ]; then
    local ENGINE_BASENAME
    ENGINE_BASENAME=$(basename "${SHIPPED_ENGINE}")
    local DST_ENGINE=${DST_DIR}/${ENGINE_BASENAME}
    if [ ! -f "${DST_ENGINE}" ] || size_differs "${SHIPPED_ENGINE}" "${DST_ENGINE}"; then
      cp "${SHIPPED_ENGINE}" "${DST_ENGINE}"
    fi
  elif [ "${ONNX_CHANGED}" = "1" ]; then
    rm -f "${DST_DIR}"/*.engine
  fi
}

stage_model peoplenet    resnet34_peoplenet_int8.onnx
stage_model movenet      movenet_singlepose_lightning.onnx
stage_model handdet      yolox_n_body_head_hand_320x320.onnx
stage_model handlandmark hand_landmark_sparse_224x224.onnx
