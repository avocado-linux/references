#!/usr/bin/env bash

set -e

# Resolve the TARGET arch from AVOCADO_SDK_TARGET, the same way the app
# compile scripts do. Do NOT probe python3/uname at runtime: the SDK
# container's arch follows the HOST (aarch64 on Apple Silicon, x86_64 on
# Intel), not the target, so runtime probes report the wrong arch whenever
# host and target differ (e.g. an arm64 Mac building for qemux86-64).
case "$AVOCADO_SDK_TARGET" in
  *x86-64*|*x86_64*) NARCH=amd64 ;;
  *)                 NARCH=arm64 ;;
esac

VER="$(curl -sfL https://api.github.com/repos/nats-io/nats-server/releases/latest \
  | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -1 | grep -oE 'v[0-9.]+')"
echo "[broker] nats-server $VER for linux-$NARCH (target $AVOCADO_SDK_TARGET)"

mkdir -p broker/bin
curl -sfL "https://github.com/nats-io/nats-server/releases/download/${VER}/nats-server-${VER}-linux-${NARCH}.tar.gz" \
  | tar xz -C broker/bin --strip-components=1 --wildcards '*/nats-server'

echo "[broker] done"
