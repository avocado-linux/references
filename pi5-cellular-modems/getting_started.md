# Getting Started with Pi 5 Cellular Modems

This guide builds a runtime that adds USB cellular modem drivers and a systemd-networkd profile to a Raspberry Pi 5, then checks the drivers and the profile on the device.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A Raspberry Pi 5 that already runs Avocado OS (2026 release, `next` channel) and is reachable over SSH
- A USB cellular modem with an active SIM and data plan, for the last check

## Initialize

```bash
avocado init --reference pi5-cellular-modems pi5-modems
cd pi5-modems
```

## Install

```bash
avocado install -f
```

## Build

```bash
avocado build
```

This builds the `cellular-modems` extension: the USB network and serial drivers (`usbnet`, `cdc_ether`, `cdc_ncm`, `cdc_mbim`, `cdc_wdm`, `qmi_wwan`, `rndis_host`, `cdc_acm`, `option`, `usb_wwan`, `usbserial`, `qcserial`, `sierra`, `sierra_net` and `tun`), `lsusb`, `ethtool` and `iproute2`, the QMI and MBIM tools from `libqmi` and `libmbim`, a networkd profile for every `usb*` and `wwan*` link, and a small unit that reloads networkd after the extension is merged.

## Deploy

Deploy to a running device over SSH, or provision a fresh SD card:

```bash
avocado deploy --device root@<device-ip> dev
# or
avocado provision -r dev --profile sd
```

## Verify

### 1. The drivers are in place

```bash
ssh root@<device-ip> 'for m in usbnet cdc_ether cdc_ncm cdc_mbim qmi_wwan option cdc_acm; do modprobe -n $m && echo "ok: $m"; done'
```

Every module prints `ok`. A modem loads the ones it needs by itself when you plug it in.

### 2. The network profile is active

networkd can start before the extension is merged, so the extension asks it to re-read its configuration twice: a unit that runs on every boot, and a merge hook that runs on every merge, including `avocadoctl refresh` on a running device. Check that a link named `usb0` gets the cellular profile, with no manual reload:

```bash
ssh root@<device-ip> 'modprobe tun; ip tuntap add dev usb0 mode tap; ip link set usb0 up; sleep 3; networkctl status usb0 --no-pager | grep "Network File"; ip link del usb0'
```

Expect `Network File: /usr/lib/systemd/network/30-cellular.network`. Without the profile, the same link would match the stock `80-wired.network` and get Ethernet's route metric.

### 3. A real modem

Plug in the modem and watch the kernel:

```bash
ssh root@<device-ip> 'lsusb; dmesg | tail -20; ip -br link; networkctl status usb0 wwan0 --no-pager'
```

An ECM, NCM or RNDIS modem shows up as `usb0` and gets an address by DHCP on its own. Once it has one, `ip route` lists a default route through it at metric 300, behind `eth0` at 10 and `wlan0` at 200.

A QMI or MBIM modem shows up as `wwan0`, but DHCP gets no reply until a data session is open, so the route check above does not apply to it yet. Open the session with `qmi-network` or `qmicli` for a QMI modem, or `mbim-network` or `mbimcli` for an MBIM one; the extension ships all four. Many modems can also be switched to ECM mode instead, after which they behave like the first case. On a Quectel modem such as the EC25 or EG25, that is `AT+QCFG="usbnet",1` on its AT port, followed by a modem reset.

### What this reference does not do

- It does not switch a modem between USB modes. Modems that start in a storage or serial mode and need an AT command to expose a network interface need that step added.
- It does not install ModemManager, so nothing sets an APN, manages the SIM or opens a QMI or MBIM data session by itself. The QMI and MBIM tools are there for you to do it.
- It does not dial PPP. The feed has no `pppd`, so a modem that only offers a serial data path gets its `/dev/ttyUSB*` ports for AT commands but no connection.
- The drivers and the profile are tested without a modem attached. Step 3 is yours to run.
