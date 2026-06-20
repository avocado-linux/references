#!/usr/bin/env bash

set -e

echo "Installing Python dependencies..."
# Start clean so app/packages only ever holds flask + its deps. numpy, cv2,
# tensorrt and the CUDA bindings come from feed packages (system site-packages)
# where they are ABI-matched to opencv; a stray PyPI numpy vendored here would
# shadow the system one and break cv2.
rm -rf app/packages
uv pip install --target app/packages --python $(which python3) flask

echo "Dependencies installed successfully"
