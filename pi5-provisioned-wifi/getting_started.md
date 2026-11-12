# Getting Started with Pi 5 Provisioned Wi-Fi

This guide builds a runtime with the Pi 5's onboard Wi-Fi under systemd-networkd, then writes the network credentials to the device's `/var` over SSH so they never appear in the image or in an extension.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A Raspberry Pi 5 that already runs Avocado OS (2026 release, `next` channel) and is reachable over SSH
- A 2.4 GHz or 5 GHz WPA2-PSK network the Pi can see, and its passphrase
- `python3` on the provisioning host

## Initialize

```bash
avocado init --reference pi5-provisioned-wifi pi5-wifi
cd pi5-wifi
```

## Install

```bash
avocado install -f
```

## Build

```bash
avocado build
```

This builds the `wifi-station` extension: `wpa_supplicant`, `iw`, a `wifi-station.service` unit that reads `/var/lib/wifi-station/wpa_supplicant.conf`, and a networkd file that runs DHCP on `wlan0` at route metric 200. The extension carries no credentials. The `brcmfmac` drivers, the Broadcom firmware and the regulatory database come from the `avocado-bsp` extension in the same runtime, which loads them with a udev trigger when it merges.

## Deploy

Deploy to a running device over SSH, or provision a fresh SD card:

```bash
avocado deploy --device root@<device-ip> dev
# or
avocado provision -r dev --profile sd
```

`wifi-station.service` is enabled but inactive at this point, because its config file does not exist yet.

## Provision the credentials

Create a two-line file with the network name and the passphrase. Keep it out of version control; the script deletes it when it finishes.

```bash
install -m 600 /dev/null wifi.txt
$EDITOR wifi.txt   # line 1: SSID, line 2: passphrase
scripts/provision-wifi.sh root@<device-ip>
```

The script derives the 64-hex WPA key on your machine and sends only that key and the SSID. Expect:

```text
root:root 700 /var/lib/wifi-station
root:root 600 /var/lib/wifi-station/wpa_supplicant.conf
network blocks: 1  psk lines of 64 hex: 1  quoted psk lines: 0
```

Then start the unit:

```bash
ssh root@<device-ip> systemctl restart wifi-station.service
```

## Verify

```bash
ssh root@<device-ip> 'wpa_cli -i wlan0 status | grep -E "^(wpa_state|ssid|ip_address)"; networkctl status wlan0 --no-pager | grep -E "State|Address|Gateway"; ping -I wlan0 -c 3 1.1.1.1'
```

Expect `wpa_state=COMPLETED`, `State: routable (configured)`, a DHCP address on `wlan0`, and replies from `1.1.1.1`. `eth0` keeps the lower route metric, so SSH over Ethernet is unaffected.

Reboot the device and run the same check without touching it. `wifi-station.service` starts on its own, and its `ExecStartPost` (`networkctl reload`) makes networkd manage `wlan0` even though networkd started before the extension was merged. The extension's `on_merge` hook restarts the unit after every merge, so a changed `25-wlan0.network` also takes effect on `avocado deploy` without a reboot. The reload lives in the unit because the merge hook runs before D-Bus is up on a cold boot, where `networkctl reload` fails with "Failed to connect to system bus".

### Changing the credentials

Run `scripts/provision-wifi.sh` again with the new SSID and passphrase, then `systemctl restart wifi-station.service` on the device. The file is replaced atomically and survives reboots.

### What this protects, and what it does not

- The passphrase never reaches the device, and the derived key appears in no process argument and not in the journal. The only copy on the device is the `0600` file under `/var`.
- Anyone who can read the device's storage can read that file and join the network. Encrypted `/var` is not enabled in this reference, and the Pi 5 has no TPM to seal it to.
- A shared passphrase across a fleet means one stolen device exposes the network. Use a passphrase per device where you can.
- The world regulatory domain applies until an access point announces a country, so 5 GHz channels and part of 2.4 GHz are scanned passively at first.
