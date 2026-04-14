---
language: Shell
targets:
  - raspberrypi4
  - raspberrypi5
topics:
  - usb-gadget
  - wifi
  - docker
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Rubicon

A full-featured development runtime for Raspberry Pi 4 and 5 with USB gadget networking, WiFi, Docker, Cockpit web management, and multi-arch container support via QEMU user-static. Connect to your Pi over USB-C with zero network configuration.

- USB gadget mode: plug in via USB-C and SSH to `rubicon.local` over a virtual Ethernet link
- WiFi via wpa_supplicant with systemd-networkd DHCP
- Docker and Cockpit pre-installed for container development and web-based management
- Serial console over USB (`ttyGS0`), Avahi/mDNS discovery, and dnsmasq DHCP for the USB network
- QEMU user-static binfmt for running multi-arch containers natively
