#!/bin/sh
# Trust-pair the currently attached iPhone with libimobiledevice.
#
# First-time pairing requires the user to tap "Trust This Computer" on the
# iPhone. After a successful pair, /var/lib/lockdown/<UDID>.plist persists,
# and subsequent reconnects come up automatically (ipheth0 / cdc-ncm netdev).
set -eu

if ! command -v idevicepair >/dev/null 2>&1; then
  echo "idevicepair not found; libimobiledevice is not installed" >&2
  exit 1
fi

if ! systemctl is-active --quiet usbmuxd.service; then
  echo "usbmuxd is not running; starting it" >&2
  systemctl start usbmuxd.service
fi

# Give usbmuxd a moment to enumerate the device after plug-in.
sleep 2

idevicepair pair
echo
echo "If this failed with 'Please accept the trust dialog', tap Trust on the"
echo "iPhone and rerun: systemctl start iphone-pair.service"
