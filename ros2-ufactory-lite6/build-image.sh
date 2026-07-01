#!/bin/sh
#
# Build the ROS 2 Lite 6 container locally and save it into the app
# extension's overlay. Run this BEFORE `avocado build`. The tarball ships
# inside the app extension's sysext, so it's delivered atomically with the
# rest of the extension via OTA — both `avocado provision` (re-flash) and
# `avocado deploy` (network update) pick up changes to it.
#
# Usage:
#   sh build-image.sh                                  # host architecture
#   TARGET_PLATFORM=linux/arm64 sh build-image.sh      # cross-build for ARM
#
# Most users want the arm64 build — all supported targets are arm64.
#

set -eu

IMAGE="lite6-ros2:latest"
OUT="overlay/app/usr/lib/container-app/lite6.tar"

mkdir -p "$(dirname "${OUT}")"

if [ -n "${TARGET_PLATFORM:-}" ]; then
  echo "Building image for ${TARGET_PLATFORM}..."
  docker buildx build \
    --platform "${TARGET_PLATFORM}" \
    --load \
    -t "${IMAGE}" \
    -f app/Dockerfile \
    app
else
  echo "Building image for host architecture..."
  docker build \
    -t "${IMAGE}" \
    -f app/Dockerfile \
    app
fi

echo "Saving to ${OUT}..."
docker save -o "${OUT}" "${IMAGE}"

SIZE=$(du -h "${OUT}" | cut -f1)
echo "Done. ${OUT} (${SIZE})"
