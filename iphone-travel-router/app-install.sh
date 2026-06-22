#!/usr/bin/env bash

# AVOCADO_BUILD_EXT_SYSROOT: extension sysroot the overlay was copied into

set -e

# NetworkManager refuses to load keyfiles whose mode is wider than 0600.
# Git tracks only the executable bit, so the file ships as 0644 from the
# overlay — fix it up at install time.
chmod 600 "$AVOCADO_BUILD_EXT_SYSROOT/etc/NetworkManager/system-connections/"*.nmconnection

chmod 755 "$AVOCADO_BUILD_EXT_SYSROOT/usr/local/bin/iphone-pair.sh"

echo "iphone-travel-router overlay installed"
