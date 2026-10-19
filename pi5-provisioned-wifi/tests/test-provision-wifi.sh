#!/usr/bin/env bash
# Host test for scripts/provision-wifi.sh. A stand-in `ssh` on the path records what the script
# would send to the device, so the derived config can be checked without a device.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../scripts/provision-wifi.sh"

pass=0
fail=0
ok() {
  printf '  ok   - %s\n' "$1"
  pass=$((pass + 1))
}
bad() {
  printf '  FAIL - %s\n' "$1"
  fail=$((fail + 1))
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"
cat >"$work/bin/ssh" <<'EOF'
#!/bin/sh
cat >"$SENT"
EOF
chmod +x "$work/bin/ssh"
export PATH="$work/bin:$PATH" SENT="$work/sent"

run() { # <input file contents as printf format> -> sets $rc, $err; the config lands in $SENT
  rm -f "$SENT"
  # shellcheck disable=SC2059 # the argument is a printf format on purpose: it carries \r and \f
  printf "$1" >"$work/wifi.txt"
  set +e
  (cd "$work" && "$script" root@unit wifi.txt >"$work/out" 2>"$work/err")
  rc=$?
  set -e
}

# The IEEE 802.11i test vector: SSID "IEEE", passphrase "password".
run 'IEEE\npassword\n'
if [[ $rc -eq 0 ]] && grep -qx $'\tpsk=f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e' "$SENT"; then
  ok "the key matches the standard test vector"
else bad "the key does not match the test vector (rc=$rc)"; fi

if grep -qx $'\tssid=49454545' "$SENT" && ! grep -q 'password' "$SENT"; then
  ok "the SSID is sent as hex and the passphrase is not sent"
else bad "the SSID or the passphrase handling is wrong: $(cat "$SENT")"; fi

if grep -qx "SSID: 'IEEE'" "$work/err"; then ok "the exact SSID is printed so the user can see what the key was derived for"; else bad "no SSID line on stderr: $(cat "$work/err")"; fi

# A file saved with Windows line endings must derive the same key as one with Unix endings.
run 'IEEE\r\npassword\r\n'
if [[ $rc -eq 0 ]] && grep -qx $'\tpsk=f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e' "$SENT" && grep -qx $'\tssid=49454545' "$SENT"; then
  ok "CRLF line endings give the same SSID and key as LF"
else bad "CRLF changed the SSID or the key"; fi

# A passphrase may contain a form feed; it is one character of the passphrase, not a line break.
want="$(python3 -I -c 'import hashlib; print(hashlib.pbkdf2_hmac("sha1", b"pass\x0cword12", b"IEEE", 4096, 32).hex())')"
run 'IEEE\npass\fword12\n'
if [[ $rc -eq 0 ]] && grep -qx $'\tpsk='"$want" "$SENT"; then
  ok "a form feed inside the passphrase is kept as part of the passphrase"
else bad "a form feed in the passphrase changed the key (rc=$rc)"; fi

# A trailing space is part of the SSID the user typed, so it is kept and made visible.
run 'IEEE \npassword\n'
if [[ $rc -eq 0 ]] && grep -qx "SSID: 'IEEE '" "$work/err" && grep -qx $'\tssid=4945454520' "$SENT"; then
  ok "a trailing space is kept and shown as part of the SSID"
else bad "a trailing space was dropped or hidden"; fi

# An SSID longer than 32 bytes cannot exist on an access point.
long="$(printf 'a%.0s' $(seq 1 33))"
run "$long"'\npassword\n'
if [[ $rc -ne 0 ]] && grep -q 'SSID must be 32 bytes or less' "$work/err" && [[ ! -s "$SENT" ]]; then
  ok "an SSID of 33 bytes is refused and nothing is sent"
else bad "a 33 byte SSID was accepted (rc=$rc)"; fi

run "$(printf 'a%.0s' $(seq 1 32))"'\npassword\n'
if [[ $rc -eq 0 ]]; then ok "an SSID of 32 bytes is accepted"; else bad "a 32 byte SSID was refused: $(cat "$work/err")"; fi

# The passphrase length rule and the two-line rule still hold.
run 'IEEE\nshort\n'
if [[ $rc -ne 0 ]] && grep -q 'passphrase must be 8 to 63 characters' "$work/err"; then ok "a 5 character passphrase is refused"; else bad "a short passphrase was accepted"; fi
run 'IEEE\n'
if [[ $rc -ne 0 ]] && grep -q 'two non-empty lines' "$work/err"; then ok "a file with only an SSID is refused"; else bad "a one-line file was accepted"; fi

# The input file is removed whatever happens.
run 'IEEE\npassword\n'
if [[ ! -e "$work/wifi.txt" ]]; then ok "the input file is removed after a successful run"; else bad "the input file was left behind"; fi
run 'IEEE\nshort\n'
if [[ ! -e "$work/wifi.txt" ]]; then ok "the input file is removed after a refused run"; else bad "the input file was left behind after a refusal"; fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
