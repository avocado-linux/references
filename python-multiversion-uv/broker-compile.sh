#!/usr/bin/env bash

set -e

# Detect the TARGET arch, not the SDK shell arch. The SDK container runs on the
# x86_64 host even for aarch64 targets (only the target python is emulated via
# binfmt), so `uname -m` would lie. The target python3 reports the real target
# arch: x86_64 for qemux86-64, aarch64 for the Pi.
TARGET_ARCH="$(python3 -c 'import platform; print(platform.machine())')"
case "$TARGET_ARCH" in
  x86_64) NARCH=amd64 ;;
  aarch64 | arm64) NARCH=arm64 ;;
  *) echo "[broker] unsupported target arch: $TARGET_ARCH" >&2; exit 1 ;;
esac

VER="$(curl -sfL https://api.github.com/repos/nats-io/nats-server/releases/latest \
  | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -1 | grep -oE 'v[0-9.]+')"
echo "[broker] nats-server $VER for linux-$NARCH (target $TARGET_ARCH)"

mkdir -p broker/bin
curl -sfL "https://github.com/nats-io/nats-server/releases/download/${VER}/nats-server-${VER}-linux-${NARCH}.tar.gz" \
  | tar xz -C broker/bin --strip-components=1 --wildcards '*/nats-server'

echo "[broker] done"
