#!/bin/sh
#
# IMX678 Camera Initialization Script for RZ/V2N HummingBoard IIoT
#
# Vendored + busybox-compatible copy of SolidRun's
# v4l2n-init-imx678-dev.sh (meta-solidrun-arm-rzg2lc/meta-rzv2n/
# recipes-support/v4l2-init-scripts/files/). The original installs to
# /root/ via the v4l2-init-scripts recipe, which doesn't survive into
# avocado's read-only rootfs at a usable path. It also uses `head -1`
# which busybox doesn't accept (busybox needs `head -n 1`).
#
# Hardware:
#   Sensor  : Sony IMX678 (4-lane MIPI CSI-2, 12-bit Bayer)
#   CSI-2   : csi-16010400.csi21
#   CRU     : cru-ip-16010000.video1
#   Media   : /dev/media0
#   Video   : /dev/video0
#
# The IMX678 outputs SRGGB12_1X12 (12-bit raw Bayer). RZ/V2N CRU does NOT
# do hardware demosaicing, so for display we use RGGB (8-bit Bayer) +
# GStreamer bayer2rgb. The image will look greyscale because the 12-bit
# sensor data is truncated to 8-bit by the CRU — known limitation.
#
# Usage: v4l2n-init-imx678.sh [resolution]
#   Resolutions: 3840x2160 (default), 1920x1080
#
# Requires SolidRun's kernel patches (meta-solidrun-arm-rzg2lc/meta-rzv2n/
# recipes-kernel/linux/6.1-solidrun/0001-media-rzg2l-cru-... and 0002-...).

set -e

MEDIA_DEV="/dev/media0"
VIDEO_DEV="/dev/video0"

SENSOR="imx678 4-001a"
CSI2="csi-16010400.csi21"
CRU="cru-ip-16010000.video1"

MEDIA_FMT="SRGGB12_1X12"
imx678_res="${1:-3840x2160}"

case "$imx678_res" in
    3840x2160|1920x1080) ;;
    *)
        echo "WARNING: $imx678_res may not be supported by the IMX678 driver."
        echo "Supported: 3840x2160, 1920x1080"
        ;;
esac

echo "Resolution: $imx678_res"

# Verify expected entities exist (busybox-compatible head).
cru_name=$(cat /sys/class/video4linux/video*/name 2>/dev/null | grep -i "CRU" | head -n 1)
csi2_name=$(cat /sys/class/video4linux/v4l-subdev*/name 2>/dev/null | grep -i "csi" | head -n 1)
sensor_name=$(cat /sys/class/video4linux/v4l-subdev*/name 2>/dev/null | grep -i "imx678" | head -n 1)

if [ -z "$cru_name" ];   then echo "ERROR: No CRU video device found";   exit 1; fi
if [ -z "$csi2_name" ];  then echo "ERROR: No MIPI CSI-2 sub-device found"; exit 1; fi
if [ -z "$sensor_name" ];then echo "ERROR: No IMX678 sensor found";       exit 1; fi

echo "Found CRU   : $cru_name"
echo "Found CSI-2 : $csi2_name"
echo "Found Sensor: $sensor_name"

echo "Configuring media pipeline for ${imx678_res} ..."
media-ctl -d $MEDIA_DEV -r
media-ctl -d $MEDIA_DEV -l "'${CSI2}':1 -> '${CRU}':0 [1]"
media-ctl -d $MEDIA_DEV -V "'${SENSOR}':0 [fmt:${MEDIA_FMT}/${imx678_res} field:none]"
media-ctl -d $MEDIA_DEV -V "'${CSI2}':0 [fmt:${MEDIA_FMT}/${imx678_res} field:none]"
media-ctl -d $MEDIA_DEV -V "'${CSI2}':1 [fmt:${MEDIA_FMT}/${imx678_res} field:none]"
media-ctl -d $MEDIA_DEV -V "'${CRU}':0  [fmt:${MEDIA_FMT}/${imx678_res} field:none]"
media-ctl -d $MEDIA_DEV -V "'${CRU}':1  [fmt:${MEDIA_FMT}/${imx678_res} field:none]"

# RGGB: 8-bit Bayer for GStreamer bayer2rgb display path.
width=$(echo "$imx678_res" | cut -dx -f1)
height=$(echo "$imx678_res" | cut -dx -f2)
v4l2-ctl -d $VIDEO_DEV --set-fmt-video=width=${width},height=${height},pixelformat=RGGB

echo "Pipeline configured (RGGB ${imx678_res})"
