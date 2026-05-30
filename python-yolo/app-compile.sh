#!/usr/bin/env bash
# Stage the app's pip dependencies into app/packages/. Runs inside the SDK
# container during `avocado build`. The contents are copied into the
# extension sysroot by app-install.sh.

set -euo pipefail

echo "Installing Python dependencies..."
mkdir -p app/packages
uv pip install --target app/packages --python "$(which python3)" flask

echo "Dependencies installed."
