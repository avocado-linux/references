#!/usr/bin/env bash

set -e

echo "Installing syslog-dashboard into extension"

DESTDIR="$AVOCADO_BUILD_EXT_SYSROOT" cmake --install app/src/build

echo "syslog-dashboard installed successfully"
