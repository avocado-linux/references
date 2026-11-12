---
language: Shell
targets:
  - raspberrypi5
topics:
  - networking
  - systemd-networkd
  - failover
  - usb
---

# Pi 5 Network Profiles

A reference runtime that lets a Raspberry Pi 5 choose, from a value stored under `/var`, what eth0 is for and the order Ethernet, Wi-Fi and a cellular modem carry traffic in. The choice is applied at boot and can be changed on a running unit, and a change that cuts the unit off goes back by itself.

- Two eth0 roles: `internet` (DHCP, carries traffic) and `local` (a static address, no DHCP client and no gateway, so it never carries the default route)
- A priority order over Ethernet, Wi-Fi and the modem, expressed as the route metrics 100, 200 and 300
- A USB Ethernet adapter becomes an internet link without naming its interface, matched by where the link comes from (USB) with known modem vendors left out, so a modem that shares the adapter's kernel driver does not get the adapter's profile
- A change is on trial until `network-profile confirm` runs, and returns to the last confirmed choice after a timeout or a reboot
- An unusable stored choice falls back to the defaults; the networkd files are generated into `/run`, so nothing depends on a writable `/etc`

See [getting_started.md](getting_started.md) for the commands and what to expect on a unit.
