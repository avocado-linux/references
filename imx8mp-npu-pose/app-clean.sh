#!/usr/bin/env bash
# SDK "clean" hook: drop the ephemeral quantization venv + build artifacts.
# Keeps app/build/movenet + app/build/rep (the fetched inputs) so a rebuild
# doesn't re-download; remove them by hand to force a fresh fetch.
set -euo pipefail
rm -rf app/build/qenv app/build/model
echo "Cleaned app/build/{qenv,model} (kept movenet/ + rep/)."
