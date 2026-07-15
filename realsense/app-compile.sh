#!/usr/bin/env bash

set -e

echo "Installing Python dependencies..."
uv pip install --target app/packages --python $(which python3) flask pyrealsense2
echo "Python dependencies installed successfully"
