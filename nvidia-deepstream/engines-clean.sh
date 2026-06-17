#!/usr/bin/env bash
set -euo pipefail
# The engines are staged fresh from prebuilt-engines/<target>/ on every build,
# so wipe the staged copy for a clean rebuild. The committed source engines
# under prebuilt-engines/ are left untouched.
rm -rf vision-engines/overlay/usr/lib/nvidia-deepstream/engines
