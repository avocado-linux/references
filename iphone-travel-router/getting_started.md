# Getting Started with iPhone Travel Router

This guide walks you through provisioning an Avocado OS device as a travel router that takes its WAN from an iPhone Personal Hotspot over USB and shares it out over Wi-Fi, with a Cockpit web UI for live management.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A Raspberry Pi 5, microSD card, USB-A to Lightning (or USB-C) cable
- An iPhone with a cellular plan that allows Personal Hotspot
- A laptop or phone with Wi-Fi to act as a downstream client

## Initialize

```bash
avocado init --reference iphone-travel-router travel-router
cd travel-router
```

## Install

```bash
avocado install -f
```

## Build

```bash
avocado build
```

This pulls `networkmanager`, `cockpit`, `cockpit-networkmanager`, `usbmuxd`, `libimobiledevice`, `dnsmasq`, `hostapd`, `iptables`, and the relevant kernel modules (`ipheth`, `cdc_ncm`, `cdc_ether`, `usbnet`, NAT bits) into a sysext+confext, and lays down a Wi-Fi AP NetworkManager profile in the overlay.

## Deploy

Insert the SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the Raspberry Pi 5 and apply power.

## Verify

### 1. Enable Personal Hotspot on the iPhone

Settings → Personal Hotspot → Allow Others to Join. Leave the iPhone unlocked for the first plug-in.

### 2. Pair the iPhone with the device

Connect the iPhone to the Pi over USB. The first time, iOS prompts **Trust This Computer?** on the iPhone — tap Trust.

SSH to the Pi (or open a Cockpit Terminal at `https://<pi-ip>:9090` once the AP is up) and run:

```bash
systemctl start iphone-pair.service
journalctl -u iphone-pair.service
```

If pairing succeeded, `idevicepair list` shows the iPhone's UDID and `/var/lib/lockdown/<UDID>.plist` exists. Subsequent reconnects come up automatically.

### 3. Confirm the WAN interface

```bash
nmcli device status
```

Look for `eth1` (or similar) in state `connected`. NetworkManager creates a "Wired connection" profile for it on first attach and uses it as the default route.

### 4. Connect a Wi-Fi client

The pre-staged AP profile broadcasts:

- SSID: `AvocadoAP`
- Password: `avocadolinux`
- LAN: `10.42.0.0/24`, gateway/DNS `10.42.0.1`

Join from a laptop or phone, open a browser, and traffic should egress through the iPhone tether.

### 5. Open the Cockpit web UI

```
https://<pi-ip>:9090
```

Log in as `root` / `avocado`. Accept the self-signed cert. Click **Networking** for the `cockpit-networkmanager` page — you can change the AP SSID/password, see live throughput, and add or modify connections.

## Customize

### Change the AP SSID and password

The simplest path is via Cockpit → Networking → `avocado-ap` → Edit. To bake a different default into the image, edit `app/overlay/etc/NetworkManager/system-connections/avocado-ap.nmconnection` and rebuild.

### Change the LAN subnet

Edit `address1=10.42.0.1/24` in the same file.

### Use Ethernet as the LAN side instead of (or in addition to) Wi-Fi

Drop a second connection file in `app/overlay/etc/NetworkManager/system-connections/`:

```ini
[connection]
id=avocado-lan
type=ethernet
interface-name=eth0
autoconnect=true

[ipv4]
method=shared
address1=10.43.0.1/24

[ipv6]
method=ignore
```

Rebuild and reprovision. NM will share the WAN to clients on either side.

### Skip the manual pair step

To auto-pair on USB attach, add a udev rule to the overlay:

```
# app/overlay/etc/udev/rules.d/99-iphone-pair.rules
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05ac", \
  TAG+="systemd", ENV{SYSTEMD_WANTS}="iphone-pair.service"
```

Note that the user still has to tap Trust on the iPhone the first time.

### Rebuild after changes

```bash
avocado build
avocado provision -r dev --profile sd
```
