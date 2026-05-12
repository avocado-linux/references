#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: The sysroot of the extension being installed into

set -e

echo "============================================"
echo "Installing DeepX Runtime (DXRT) into extension"
echo "============================================"

STAGING_DIR="${AVOCADO_BUILD_DIR}/dx-rt-staging"

if [ ! -d "$STAGING_DIR/usr/local" ]; then
    echo "ERROR: Staging directory not found: $STAGING_DIR"
    echo "Run the compile step first."
    exit 1
fi

# Install libraries and headers into the extension sysroot
echo "Copying DXRT libraries and headers..."
cp -a "$STAGING_DIR/usr" "$AVOCADO_BUILD_EXT_SYSROOT/"

# Install the dxrt systemd service unit
SERVICE_DIR="${AVOCADO_BUILD_EXT_SYSROOT}/usr/lib/systemd/system"
mkdir -p "$SERVICE_DIR"

if [ -f "${AVOCADO_BUILD_DIR}/dx_rt/service/dxrt.service" ]; then
    install -m 0644 "${AVOCADO_BUILD_DIR}/dx_rt/service/dxrt.service" "$SERVICE_DIR/"
elif [ -f "dx_rt/service/dxrt.service" ]; then
    install -m 0644 "dx_rt/service/dxrt.service" "$SERVICE_DIR/"
else
    echo "WARNING: dxrt.service not found; skipping service installation"
fi

echo "DXRT installed successfully!"
echo "  Libraries: ${AVOCADO_BUILD_EXT_SYSROOT}/usr/local/lib/"
echo "  Headers:   ${AVOCADO_BUILD_EXT_SYSROOT}/usr/local/include/"
echo "  Daemon:    ${AVOCADO_BUILD_EXT_SYSROOT}/usr/local/bin/dxrtd"
echo "  Service:   ${SERVICE_DIR}/dxrt.service"
