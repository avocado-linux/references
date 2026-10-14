#!/usr/bin/env bash
# Derive the WPA-PSK key for a Wi-Fi network on THIS machine and store only the
# derived key on the device, root-only, under /var. The passphrase never reaches
# the device.
#
# Usage: scripts/provision-wifi.sh <user@host> [input-file]
#
# The input file has two lines: the SSID, then the passphrase. It defaults to
# ./wifi.txt and is deleted when the script exits.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <user@host> [input-file]" >&2
  exit 2
fi
HOST="$1"
IN="${2:-wifi.txt}"
trap 'rc=$?; rm -f "$IN"; echo "provision-wifi: exit $rc (input file removed)"' EXIT

[[ -s $IN ]] || { echo "missing or empty $IN" >&2; exit 2; }

# PBKDF2-HMAC-SHA1, 4096 rounds, SSID as salt, 32 bytes: the derivation
# wpa_passphrase performs. wpa_passphrase is not used because it needs a
# terminal on stdin and prints nothing over ssh. The SSID is written as hex so
# any character is safe.
conf=$(python3 -I - "$IN" <<'PY'
import hashlib, sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
if len(lines) < 2 or not lines[0] or not lines[1]:
    sys.exit("input needs two non-empty lines: SSID, then passphrase")
ssid, pw = lines[0].encode(), lines[1].encode()
if not 8 <= len(pw) <= 63:
    sys.exit("passphrase must be 8 to 63 characters")
psk = hashlib.pbkdf2_hmac("sha1", pw, ssid, 4096, 32).hex()
print("ctrl_interface=DIR=/run/wpa_supplicant GROUP=0")
print("update_config=0")
print("network={")
print("\tssid=" + ssid.hex())
print("\tpsk=" + psk)
print("\tkey_mgmt=WPA-PSK")
print("}")
PY
)

# Device side: a 0700 directory and a 0600 file, replaced atomically, then a
# check that the config has the shape wpa_supplicant needs.
remote='
set -eu
umask 077
dir=/var/lib/wifi-station
mkdir -p "$dir"
chmod 700 "$dir"
cat > "$dir/wpa_supplicant.conf.new"
chmod 600 "$dir/wpa_supplicant.conf.new"
mv "$dir/wpa_supplicant.conf.new" "$dir/wpa_supplicant.conf"
stat -c "%U:%G %a %n" "$dir" "$dir/wpa_supplicant.conf"
echo "network blocks: $(grep -c "^network=" "$dir/wpa_supplicant.conf")  psk lines of 64 hex: $(grep -cE "^[[:space:]]psk=[0-9a-f]{64}$" "$dir/wpa_supplicant.conf")  quoted psk lines: $(grep -cE "psk=\"" "$dir/wpa_supplicant.conf" || true)"
'

printf '%s\n' "$conf" | ssh "$HOST" "sh -c '$remote'"
echo "Expected: network blocks: 1  psk lines of 64 hex: 1  quoted psk lines: 0"
echo "Start it now with: ssh $HOST systemctl restart wifi-station.service"
