#!/usr/bin/env bash

set -e

PYVER=3.11
APPDIR=app311

# Install a standalone CPython (python-build-standalone) for the TARGET arch.
# Inside the SDK container uv detects the target arch automatically: native
# x86_64 for qemux86-64, emulated aarch64 for raspberrypi5. The interpreter and
# every wheel installed against it therefore match the device.
export UV_PYTHON_INSTALL_DIR="$PWD/$APPDIR/uv-python"

echo "[$APPDIR] installing CPython $PYVER via uv..."
uv python install "$PYVER"

PYROOT="$(ls -d "$UV_PYTHON_INSTALL_DIR"/cpython-${PYVER}.*/ | sort -V | tail -1)"
PYROOT="${PYROOT%/}"
PYBIN="$PYROOT/bin/python${PYVER}"
echo "[$APPDIR] interpreter: $PYBIN"

echo "[$APPDIR] installing deps against CPython $PYVER..."
uv pip install --target "$APPDIR/packages" --python "$PYBIN" \
  numpy \
  nats-py

# Stage the relocatable interpreter tree for the install step to place on-device
# at /usr/lib/$APPDIR/python.
rm -rf "$APPDIR/python"
mkdir -p "$APPDIR/python"
cp -a "$PYROOT/." "$APPDIR/python/"

echo "[$APPDIR] done"
