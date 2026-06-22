#!/usr/bin/env bash

# Fetches a sample looping video for the demo. The defaults mimic the
# footage a battery-powered smart camera (Ring / Nest / Arlo-style) would
# capture, so YOLOv3-COCO has plenty of person / vehicle targets to draw
# boxes around.
#
# Default: 15s 1080p clip of a busy NYC sidewalk — pedestrian crossing,
# UPS truck, yellow cab. Multiple classes per frame, ~8MB H.264 MP4.
# Pexels free-license, hot-linkable CDN URL.
#
# Override URL via `VIDEO_URL=<url> ./fetch-video.sh`.
#
# Other curated alternatives (uncomment to swap):
# - Front-door delivery (canonical doorbell-cam scenario, 5MB, 11s):
#     https://videos.pexels.com/video-files/6667244/6667244-hd_1920_1080_25fps.mp4
# - Suburban couple walking past house (6MB, ~10s):
#     https://videos.pexels.com/video-files/7578719/7578719-hd_1920_1080_30fps.mp4

set -euo pipefail

VIDEO_URL="${VIDEO_URL:-https://videos.pexels.com/video-files/854100/854100-hd_1920_1080_25fps.mp4}"
DEST="app/overlay/usr/lib/rzv2n-drpai-yolo/sample.mp4"

echo "============================================"
echo "Fetching sample video"
echo "  url:  ${VIDEO_URL}"
echo "  dest: ${DEST}"
echo "============================================"

mkdir -p "$(dirname "$DEST")"

if [ -f "$DEST" ] && [ -s "$DEST" ]; then
    echo "Already present at $DEST (skip — delete to refetch)"
else
    curl -fsSL "$VIDEO_URL" -o "$DEST"
fi

ls -lh "$DEST"
echo "Done."
