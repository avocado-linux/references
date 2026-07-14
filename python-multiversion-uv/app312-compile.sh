#!/usr/bin/env bash

set -e

# app312 runs on the SDK's own Python (3.12 on the 2024 scarthgap SDK), which is
# the same interpreter the device ships as /usr/bin/python3. Deps are resolved
# against it, matching the Yocto build system's Python exactly.
echo "[app312] SDK python: $(python3 --version)"
echo "[app312] installing deps against the system Python..."
uv pip install --target app312/packages --python "$(which python3)" \
  numpy \
  nats-py \
  mcap

echo "[app312] done"
