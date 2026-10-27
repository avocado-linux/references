---
language: Shell
targets:
  - raspberrypi5
topics:
  - cellular
  - modem
  - networking
  - usb
  - systemd-networkd
---

# Pi 5 Cellular Modems

A reference runtime that adds USB cellular modem support to a Raspberry Pi 5. The stock image builds the drivers but leaves them out of the rootfs; this extension brings in the ones a modem needs and a systemd-networkd profile for the link it creates.

- Cover the common USB modes: ECM and NCM (`usb0`), QMI and MBIM (`wwan0`), RNDIS, and serial AT ports
- Give the modem link a route metric of 300, behind Ethernet and Wi-Fi, so it carries traffic only when they have no route
- Reload networkd on every extension merge, so a changed profile takes effect without a reboot
- Keep the default rootfs unchanged: nothing here is installed unless you build the extension
