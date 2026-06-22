---
language: Shell
targets:
  - raspberrypi5
topics:
  - networking
  - nat
  - web
  - ios
  - cockpit
---

# iPhone Travel Router

A reference runtime that turns an Avocado OS device into a travel router. Plug an iPhone in over USB to take its Personal Hotspot as the WAN, share the connection out over a Wi-Fi access point, and manage everything from a Cockpit web UI.

- Use NetworkManager `ipv4.method=shared` for one-line NAT + DHCP + DNS to LAN clients
- Run `usbmuxd` + `libimobiledevice` so the iPhone trusts the host and exposes `ipheth0`
- Pre-stage a Wi-Fi AP NetworkManager profile that auto-starts on boot
- Expose Cockpit (with `cockpit-networkmanager`) on `https://<device>:9090` for live config
