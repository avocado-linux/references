#!/usr/bin/env bash
# Clean hook: drop build artifacts (quantizer venv + generated model).
# Leaves app/build/rep/ (the fetched representative images) in place so a
# rebuild doesn't re-download them; remove it by hand to force a refetch.
set -euo pipefail
rm -rf app/build/qenv app/build/model
echo "Cleaned app/build/qenv and app/build/model (kept app/build/rep)"
