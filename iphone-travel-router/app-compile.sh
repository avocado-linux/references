#!/usr/bin/env bash

# Nothing to compile — this reference is configuration-only. NetworkManager,
# Cockpit, usbmuxd, and libimobiledevice are pulled in as runtime packages
# by avocado.yaml and configured via the overlay.

set -e
echo "iphone-travel-router: no compile step (config-only reference)"
