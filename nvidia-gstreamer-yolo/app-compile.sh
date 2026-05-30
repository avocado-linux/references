#!/usr/bin/env bash

set -e

echo "Installing Python dependencies..."
uv pip install --target app/packages --python $(which python3) flask

echo "Dependencies installed successfully"
