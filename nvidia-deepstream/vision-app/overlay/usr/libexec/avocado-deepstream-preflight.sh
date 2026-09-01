#!/bin/sh
#
# Pre-start workaround for the vision pipeline on Avocado OS.
#
# Avocado is an immutable OS: only /var is writable at runtime, and /run is a
# tmpfs. This script writes ONLY to /run (gone at reboot, rebuilt on each
# start). It never overlays, bind-mounts, or otherwise touches /usr, /etc, or
# /opt — those paths are managed exclusively by the sysext/confext A/B
# mechanism and any in-place modification will break `avocado runtime deploy`
# (systemd-sysext's unmerge bails on "Read-only file system" if anything is
# mounted onto the path it needs to walk).
#
# Note: this script no longer stages models or engines into /var. The ONNX
# files (vision-models extension) and the prebuilt TensorRT engines
# (vision-engines extension) are both shipped read-only under /usr/lib/
# nvidia-deepstream/ and the nvinfer configs point straight at them. nvinfer
# memory-maps the prebuilt engine on load — no write, so no writable staging
# directory is required. Shipping the engine in the extension (rather than
# compiling it on-device into /var) keeps it dm-verity-verified and OTA-able,
# which is why every supported target must ship a prebuilt engine.
#
# Only one preparation remains before the python app builds its pipeline:
# curate a GStreamer plugin scan directory that excludes
# libcustom2d_preprocess.so.
#
#   The deepstream-9.1 package installs a helper library at
#   /usr/lib/gstreamer-1.0/deepstream/libcustom2d_preprocess.so. It is not a
#   GStreamer plugin (it's used by nvdspreprocess, which this reference
#   doesn't use), but the plugin scanner subprocess loads every .so in that
#   directory. Its dlopen-time constructors trigger
#   `pthread_setspecific: Invalid argument` inside glib; the scanner aborts
#   and on its synchronous-load recovery path the parent blacklists the *next*
#   file in alphabetical order — libgstnvvideoconvert.so. The symptom is
#   `gst_parse_error: no element "nvvideoconvert"`.
#
#   We build a directory under /run with symlinks to every real plugin EXCEPT
#   libcustom2d_preprocess.so, and point GST_PLUGIN_SYSTEM_PATH_1_0 at it from
#   vision-app.service. GStreamer scans only that directory, so the bad
#   library is never opened.

set -eu

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
