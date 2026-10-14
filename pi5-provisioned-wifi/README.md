---
language: Shell
targets:
  - raspberrypi5
topics:
  - wifi
  - networking
  - credentials
  - systemd-networkd
---

# Pi 5 Provisioned Wi-Fi

A reference runtime that brings up the Raspberry Pi 5's onboard Wi-Fi under systemd-networkd with credentials that are never part of the image or an extension. The device receives only the derived WPA key, written root-only under `/var` at provisioning time.

- Ship `wpa_supplicant`, the radio's drivers and firmware, and a unit that stays inactive until its config exists
- Keep the config in `/var/lib/wifi-station/` (directory `0700`, file `0600`), because `/etc` on a running device does not survive a reboot
- Derive the key on the provisioning host, so the passphrase never reaches the device
- Ask networkd to re-read its configuration after the extension merge, so `wlan0` is managed on a cold boot
