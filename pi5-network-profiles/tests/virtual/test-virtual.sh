#!/bin/sh
# Virtual-layer scenarios of the AirGarage network test plan, run ON a Pi 5 that has the
# network-profiles extension merged and eth0 on a DHCP network. Run it as root:
#
#     sh test-virtual.sh
#
# It stands in for the links a unit does not have with veth pairs, each with a DHCP server
# (busybox udhcpd) on the far end, and checks routes, metrics and penalties. It never touches
# eth0's address, so an SSH session over eth0 survives. It needs the `veth` kernel module (the
# image does not build it in; kernel-module-veth from the feed is enough, copied to
# /var/tmp/veth.ko) and a udev rule it writes itself to mark one link as a USB Ethernet
# adapter, because a veth has no USB parent.
#
# Scenarios by the ids of the test plan: B2, B5, C4, C5, C6, D1, D4 (the networkd side), A4.

set -u

pass=0
fail=0
ok() { printf '  ok   - %s\n' "$1"; pass=$((pass + 1)); }
bad() {
    printf '  FAIL - %s\n' "$1"
    fail=$((fail + 1))
    ip -4 route show default | sed 's/^/           default: /'
}
check() { # <description> <command...>
    description="$1"
    shift
    if "$@"; then ok "$description"; else bad "$description"; fi
}

W=/tmp/np-virtual
RUN=/run/systemd/network
mkdir -p "$W"

for tool in ip networkctl udhcpd udevadm resolvectl; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing $tool"; exit 2; }
done
if ! ip link add npprobe type veth peer name npprobep 2>/dev/null; then
    [ -f /var/tmp/veth.ko ] && insmod /var/tmp/veth.ko 2>/dev/null
    ip link add npprobe type veth peer name npprobep 2>/dev/null || { echo "no veth driver: load kernel-module-veth first"; exit 2; }
fi
ip link del npprobe

# The far end of each veth is the test's own DHCP server, so networkd must leave it alone. The
# stock 80-wired.network matches every Ethernet-type link: without this, networkd runs a DHCP
# client on the server's end and removes the address the server needs.
cat >"$RUN/05-np-test-peers.network" <<'EOF'
[Match]
Name=usb0p ugnic0p sensor0p

[Link]
Unmanaged=yes
EOF
networkctl reload

cleanup() {
    for pid in "$W"/srv-*.pid; do [ -f "$pid" ] && kill "$(cat "$pid")" 2>/dev/null; done
    for link in usb0 ugnic0 sensor0; do ip link del "$link" 2>/dev/null; done
    rm -rf "$RUN/10-np-eth0.network.d" "$RUN/10-np-cellular.network.d" "$RUN"/10-np-test-*.network "$RUN/05-np-test-peers.network" /run/udev/rules.d/99-np-test.rules
    udevadm control --reload
    network-profile apply >/dev/null 2>&1 || true
    rm -rf "$W"
}
trap cleanup EXIT

# A link NAME with a DHCP server on its far end PEER. The far end is 10.77.<n>.1/24 and
# hands out 10.77.<n>.50, with itself as the router and the DNS server.
mklink() { # <name> <peer> <n> [extra address on the peer]
    name="$1" peer="$2" n="$3"
    ip link add "$name" type veth peer name "$peer"
    ip addr add "10.77.$n.1/24" dev "$peer"
    [ -z "${4:-}" ] || ip addr add "$4" dev "$peer"
    ip link set "$peer" up
    cat >"$W/udhcpd-$n.conf" <<EOF
start 10.77.$n.50
end 10.77.$n.60
interface $peer
option subnet 255.255.255.0
option router 10.77.$n.1
option dns 10.77.$n.1
lease_file $W/leases-$n
pidfile $W/udhcpd-$n.pid
EOF
    : >"$W/leases-$n"
    udhcpd -f "$W/udhcpd-$n.conf" >"$W/udhcpd-$n.log" 2>&1 &
    echo $! >"$W/srv-$n.pid"
    sleep 1
    ip link set "$name" up
}

metric_via() { ip -4 route show default dev "$1" | sed -n 's/.* metric \([0-9][0-9]*\).*/\1/p' | head -1; }
has_default_via() { [ -n "$(metric_via "$1")" ]; }
no_default_via() { [ -z "$(metric_via "$1")" ]; }
metric_is() { [ "$(metric_via "$1")" = "$2" ]; }
best_dev() { ip -4 route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1; }
best_is() { [ "$(best_dev)" = "$1" ]; }
file_of() { networkctl status "$1" --no-pager 2>/dev/null | sed -n 's/.*Network File: //p' | head -1; }
file_is() { [ "$(basename "$(file_of "$1")")" = "$2" ]; }
link_up() { ip -o link show "$1" | grep -q LOWER_UP; }
addr_of() { ip -4 addr show "$1" | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' | head -1; }
has_addr() { ip -4 addr show "$1" | grep -q "inet $2"; }
# A networkd drop-in belongs to a .network FILE, not to a link: it goes in <file>.d next to the
# file `networkctl status` names for the link, and applies to every link that file matches.
penalize() { # <link> <metric>   (the drop-in tripwire would write)
    dropin="$RUN/$(basename "$(file_of "$1")").d"
    mkdir -p "$dropin"
    printf '[DHCPv4]\nRouteMetric=%s\n' "$2" >"$dropin/penalty.conf"
    networkctl reload && networkctl reconfigure "$1"
}
unpenalize() {
    rm -rf "$RUN/$(basename "$(file_of "$1")").d"
    networkctl reload && networkctl reconfigure "$1"
}

# The leases server <n> has handed out. SIGUSR1 makes udhcpd write them to its lease file, which
# always carries a header, so an empty file does not mean no leases: read it with dumpleases.
leases_of() {
    kill -USR1 "$(cat "$W/srv-$1.pid")" 2>/dev/null
    sleep 1
    busybox dumpleases -f "$W/leases-$1"
}
lease_given() { leases_of "$1" | grep -q "10\\.77\\.$1\\.50"; }

# Wait up to 20 s for a command to succeed.
waitfor() {
    i=0
    while [ "$i" -lt 20 ]; do
        "$@" && return 0
        i=$((i + 1))
        sleep 1
    done
    return 1
}

network-profile apply >/dev/null || { echo "network-profile apply failed"; exit 2; }
waitfor has_default_via eth0 || { echo "eth0 has no default route; this test needs eth0 on a DHCP network"; exit 2; }

echo "== B2: eth0 and a modem link (usb0) up together"
mklink usb0 usb0p 1
waitfor has_default_via usb0
check "eth0 has a default route at metric 100" metric_is eth0 100
check "usb0 has a default route at metric 300" metric_is usb0 300
check "the modem link matched the cellular file" file_is usb0 10-np-cellular.network
check "traffic leaves through eth0" best_is eth0
check "the test's DHCP server handed usb0 its lease (the control for the sensor link below)" lease_given 1

echo "== C4: eth0's health check fails and tripwire writes a penalty"
addr_before="$(addr_of eth0)"
penalize eth0 2100
waitfor metric_is eth0 2100
check "eth0's default metric is the base plus 2000" metric_is eth0 2100
check "traffic moves to usb0" best_is usb0
check "eth0 keeps its address" has_addr eth0 "$addr_before"
check "eth0 keeps its carrier" link_up eth0

echo "== C5: a lease renews on a link with a penalty"
networkctl renew eth0 >/dev/null 2>&1
sleep 4
check "the penalty survives a renewal" metric_is eth0 2100

echo "== C6: every link has a penalty"
penalize usb0 2300
waitfor metric_is usb0 2300
check "eth0 stays at 2100 and usb0 is at 2300, so the order is unchanged" metric_is eth0 2100
check "a default route still exists" has_default_via eth0
check "no link was taken down" link_up usb0
check "traffic still leaves through eth0" best_is eth0

echo "== C4 recovery: the penalties are removed"
unpenalize eth0
unpenalize usb0
waitfor metric_is eth0 100
waitfor metric_is usb0 300
check "eth0 is back at 100" metric_is eth0 100
check "eth0 wins again" best_is eth0
check "usb0 is back at 300" metric_is usb0 300

echo "== D4 and B5: a USB Ethernet adapter next to eth0 and a modem"
mkdir -p /run/udev/rules.d
echo 'SUBSYSTEM=="net", KERNEL=="ugnic0", ENV{AVOCADO_USB_NIC}="1"' >/run/udev/rules.d/99-np-test.rules
udevadm control --reload
mklink ugnic0 ugnic0p 2
udevadm settle
waitfor has_default_via ugnic0
check "the adapter matched the USB Ethernet file" file_is ugnic0 10-np-usb-ethernet.network
check "the adapter gets metric 100" metric_is ugnic0 100
check "the modem keeps metric 300 beside it" metric_is usb0 300
check "eth0 keeps metric 100" metric_is eth0 100
echo "  info - with eth0 and the adapter both at 100, traffic leaves through $(best_dev)"
check "both links at the same metric stay up" link_up ugnic0
ip link del ugnic0
rm -f /run/udev/rules.d/99-np-test.rules

echo "== D1 and A4: local-only eth0 with a DHCP server on the sensor network"
scratch="$W/np-run"
NETWORK_PROFILE_STATE_DIR="$W/np-state" NETWORK_PROFILE_RUN_DIR="$scratch" NETWORK_PROFILE_NO_RELOAD=1 \
    network-profile set --confirmed eth0_role=local >/dev/null
sed 's/^Name=eth0$/Name=sensor0/' "$scratch/10-np-eth0.network" >"$RUN/10-np-test-sensor0.network"
networkctl reload
mklink sensor0 sensor0p 3 172.168.1.10/24
sleep 5
check "the local-only file applied to the sensor link" file_is sensor0 10-np-test-sensor0.network
check "the sensor link has the static address" has_addr sensor0 172.168.1.123/24
no_lease() { ! ip -4 addr show sensor0 | grep -q '10.77.3.'; }
check "no DHCP lease was taken (no 10.77.3.x address)" no_lease
# The server must be alive, or "it handed out nothing" proves nothing; the same server design
# handed out a lease to usb0 above, which is the positive control.
server_alive() { kill -0 "$(cat "$W/srv-3.pid")" 2>/dev/null; }
check "the DHCP server on the sensor network is running" server_alive
no_request() {
    if leases_of 3 | grep -q '10\.77\.3\.'; then
        echo "           the server handed out:"
        leases_of 3 | sed 's/^/             /'
        return 1
    fi
    if networkctl status sensor0 --no-pager 2>/dev/null | grep -q 'DHCP4'; then
        echo "           networkctl status mentions DHCP4:"
        networkctl status sensor0 --no-pager | grep 'DHCP4' | sed 's/^/             /'
        return 1
    fi
}
check "the DHCP server on the sensor network handed out no lease and the link runs no DHCP client" no_request
check "the sensor link has no default route" no_default_via sensor0
dns_unused() { ! resolvectl status sensor0 2>/dev/null | grep -q '10.77.3.1'; }
check "the DNS server it offered is not used" dns_unused
check "the internet default route is still eth0's" best_is eth0

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
