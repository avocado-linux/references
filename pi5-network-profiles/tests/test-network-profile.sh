#!/usr/bin/env bash
# Host test for overlay/usr/bin/network-profile. It runs the script against a scratch state
# directory and a scratch networkd directory, with the networkctl and systemd-run steps
# switched off, and checks the files it writes and the state it keeps. The networkd and
# timer behaviour on a unit is covered by the steps in getting_started.md.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tool="$here/../overlay/usr/bin/network-profile"

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
check() { # <description> <command...>
  local description="$1"
  shift
  if "$@"; then ok "$description"; else bad "$description"; fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export NETWORK_PROFILE_STATE_DIR="$work/state"
export NETWORK_PROFILE_RUN_DIR="$work/run"
export NETWORK_PROFILE_NO_RELOAD=1

np() { "$tool" "$@"; }
reset() { rm -rf "$work/state" "$work/run"; }
has() { grep -qxF -- "$2" "$1"; }
lacks() { ! grep -qF -- "$2" "$1"; }
metric() { sed -n 's/^RouteMetric=//p' "$1"; }
eth0="$work/run/10-np-eth0.network"
usb="$work/run/10-np-usb-ethernet.network"
wlan="$work/run/10-np-wlan0.network"
cell="$work/run/10-np-cellular.network"

# Defaults: eth0 is an internet link and the metrics are 100, 200 and 300.
reset
np apply >/dev/null
check "defaults give eth0 DHCP at metric 100" bash -c "grep -qx 'DHCP=ipv4' '$eth0' && [[ \$(sed -n 's/^RouteMetric=//p' '$eth0') == 100 ]]"
check "defaults give Wi-Fi metric 200" test "$(metric "$wlan")" = 200
check "defaults give the modem metric 300" test "$(metric "$cell")" = 300
check "a USB Ethernet adapter gets the Ethernet metric and matches by property" bash -c "[[ \$(sed -n 's/^RouteMetric=//p' '$usb') == 100 ]] && grep -qx 'Property=AVOCADO_USB_NIC=1' '$usb'"
sorts_ahead() {
  local f n=0
  for f in "$work"/run/*.network; do
    [[ "$(basename "$f")" < "80-wired.network" ]] || return 1
    n=$((n + 1))
  done
  [[ "$n" -eq 4 ]]
}
check "the four generated files sort ahead of the stock 80-wired.network" sorts_ahead

# Priority: a permutation changes all three metrics together.
reset
np set --confirmed priority=modem,wifi,eth >/dev/null
check "modem first gives metrics modem 100, wifi 200, eth 300" bash -c "[[ \$(sed -n 's/^RouteMetric=//p' '$cell') == 100 && \$(sed -n 's/^RouteMetric=//p' '$wlan') == 200 && \$(sed -n 's/^RouteMetric=//p' '$eth0') == 300 ]]"
check "a confirmed change is stored as the last good choice" cmp -s "$work/state/choice" "$work/state/last-good"
check "a confirmed change leaves nothing on trial" test ! -e "$work/state/unconfirmed"

# Local-only eth0: a static address, no DHCP, no gateway, not required for online.
reset
np set --confirmed eth0_role=local >/dev/null
check "eth0 local has the default sensor address" has "$eth0" "Address=172.168.1.123/24"
check "eth0 local runs no DHCP client" has "$eth0" "DHCP=no"
check "eth0 local has no gateway" lacks "$eth0" "Gateway"
check "eth0 local has no route metric at all" lacks "$eth0" "RouteMetric"
check "eth0 local is not required for online" has "$eth0" "RequiredForOnline=no"
check "eth0 local keeps DNS off its link" has "$eth0" "DNSDefaultRoute=no"
np set --confirmed local_address=10.20.30.40/16 >/dev/null
check "a custom local address is used" has "$eth0" "Address=10.20.30.40/16"

# A change on trial: applied at once, last good kept, revert and confirm.
reset
np set --confirmed priority=eth,modem,wifi >/dev/null
np set eth0_role=local >/dev/null
check "a change on trial is applied" has "$eth0" "DHCP=no"
check "a change on trial is marked" test -e "$work/state/unconfirmed"
check "a change on trial keeps the last confirmed choice" bash -c "grep -qx 'eth0_role=internet' '$work/state/last-good' && grep -qx 'priority=eth,modem,wifi' '$work/state/last-good'"
np revert >/dev/null
check "revert restores the last confirmed eth0 role" has "$eth0" "DHCP=ipv4"
check "revert restores the last confirmed priority" test "$(metric "$cell")" = 200
check "revert clears the trial" test ! -e "$work/state/unconfirmed"
np set eth0_role=local >/dev/null
np confirm >/dev/null
check "confirm stores the change as the last good choice" cmp -s "$work/state/choice" "$work/state/last-good"
check "confirm keeps the change in force" has "$eth0" "DHCP=no"
check "confirm clears the trial" test ! -e "$work/state/unconfirmed"
np revert >/dev/null
check "revert with nothing on trial changes nothing" has "$eth0" "DHCP=no"

# A reboot before confirm goes back to the last confirmed choice.
reset
np set --confirmed priority=wifi,eth,modem >/dev/null
np set eth0_role=local priority=modem,wifi,eth >/dev/null
np apply --boot >/dev/null
check "boot with an unconfirmed change goes back to the last confirmed one" bash -c "grep -qx 'DHCP=ipv4' '$eth0' && [[ \$(sed -n 's/^RouteMetric=//p' '$wlan') == 100 ]]"
check "boot with an unconfirmed change clears the trial" test ! -e "$work/state/unconfirmed"

# The first change with nothing confirmed before falls back to the defaults.
reset
np set eth0_role=local >/dev/null
np revert >/dev/null
check "revert with nothing ever confirmed goes back to the defaults" has "$eth0" "DHCP=ipv4"
check "revert with nothing ever confirmed leaves a default choice" bash -c "grep -qx 'eth0_role=internet' '$work/state/choice' || test ! -e '$work/state/choice'"

# Invalid input changes nothing and says why.
reset
np set --confirmed priority=wifi,eth,modem >/dev/null
before="$(cat "$work/state/choice")"
expect_refused() { # <description> <args...>
  local description="$1"
  shift
  if out="$(np set "$@" 2>&1)"; then bad "$description was accepted"; else
    if [[ "$(cat "$work/state/choice")" == "$before" && ! -e "$work/state/unconfirmed" ]]; then ok "$description is refused and changes nothing"; else bad "$description changed the stored choice"; fi
  fi
}
expect_refused "an unknown eth0 role" eth0_role=wan
expect_refused "a priority missing a link" priority=eth,wifi
expect_refused "a priority repeating a link" priority=eth,eth,wifi
expect_refused "an unknown key" speed=fast
expect_refused "an address with a bad octet" eth0_role=local local_address=300.1.1.1/24
expect_refused "an address with no prefix" local_address=10.0.0.1
expect_refused "an address with a prefix of 0" local_address=10.0.0.1/0
expect_refused "a timeout that is not a number" --timeout soon eth0_role=local
expect_refused "a timeout shorter than ten seconds" --timeout 5 eth0_role=local
expect_refused "no setting at all" --confirmed
out="$(np set eth0_role=wan 2>&1 || true)"
check "the refusal names the bad value" bash -c "[[ '$out' == *'eth0_role must be internet or local'* ]]"

# A damaged choice file is never half applied: the defaults are used and the file is kept.
reset
mkdir -p "$work/state"
printf 'eth0_role=local\npriority=bogus\n' >"$work/state/choice"
out="$(np apply --boot 2>&1)"
check "a damaged choice file falls back to the defaults" has "$eth0" "DHCP=ipv4"
check "a damaged choice file is reported" bash -c "[[ '$out' == *'not usable'* ]]"
check "a damaged choice file is kept for inspection" grep -qx 'priority=bogus' "$work/state/choice"

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
