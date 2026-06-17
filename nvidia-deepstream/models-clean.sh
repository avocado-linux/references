#!/usr/bin/env bash
set -euo pipefail
# Leave the committed ONNX files in place; only clear any transient deps the
# MoveNet rewrite step may have unpacked. The downloads are idempotent
# (models-compile.sh skips files that already exist), so there is nothing
# else to remove for a clean rebuild.
rm -rf vision-models/packages
