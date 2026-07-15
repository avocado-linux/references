#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: the sysroot of the extension being installed into.

set -e

echo "[broker] installing nats-server into extension"
mkdir -p "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin"
install -m 0755 broker/bin/nats-server "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin/nats-server"

echo "[broker] installed"
