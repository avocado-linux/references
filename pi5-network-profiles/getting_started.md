# Getting started

Build the runtime, deploy it to a Raspberry Pi 5, then choose a profile on the unit.

```bash
avocado install -f
avocado build
avocado deploy dev -d root@<unit-address>
```

On the unit, `network-profile` is on the path. Every command below was run on a Pi 5; the output shown is what it printed.

## See what is in force

```bash
network-profile show
```

```text
eth0_role=internet
priority=eth,wifi,modem
local_address=172.168.1.123/24
metrics: eth=100 wifi=200 modem=300
state: no choice stored, defaults in force
default routes:
  default via 192.168.8.1 dev eth0 proto dhcp src 192.168.8.201 metric 100
```

The image's own `80-wired.network` gives eth0 metric 10. With this extension merged, `networkctl status eth0` names `/run/systemd/network/10-np-eth0.network` as the file in use and the metric is 100. It stays 100 after a DHCP renewal (`networkctl renew eth0`).

## Settings

| Key | Values | Meaning |
|---|---|---|
| `eth0_role` | `internet`, `local` | `internet`: eth0 takes DHCP and carries traffic. `local`: eth0 gets `local_address`, no DHCP client, no gateway, so it never carries the default route. |
| `priority` | a list of `eth`, `wifi`, `modem`, best first, each once | The order links carry traffic in, as the route metrics 100, 200 and 300. |
| `local_address` | `A.B.C.D/N` | The static address of eth0 when `eth0_role=local`. Default `172.168.1.123/24`. |

## Change the order of the links

Prefer the modem, then Wi-Fi, then Ethernet:

```bash
network-profile set --confirmed priority=modem,wifi,eth
```

```text
network-profile: applied eth0_role=internet priority=modem,wifi,eth local_address=172.168.1.123/24
```

`network-profile show` then reports `metrics: eth=300 wifi=200 modem=100`, and the default route over eth0 has metric 300. `--confirmed` stores the choice at once; use it for a change that cannot cut the unit off, or when you are at the unit.

## Change something that could cut the unit off

Without `--confirmed` a change is on trial. It is applied at once, and the unit goes back to the last confirmed choice unless you confirm in time. This is how a remote unit stays reachable after a wrong choice.

```bash
network-profile set --timeout 60 eth0_role=local
```

```text
network-profile: applied eth0_role=local priority=eth,wifi,modem local_address=172.168.1.123/24
network-profile: on trial for 60 s: run 'network-profile confirm' before then, or the unit goes back
```

On a unit whose only link was eth0 on the internet, this cut the session two seconds later. Nothing confirmed it, and the unit went back by itself at 60 s:

```text
network-profile: the change was not confirmed in time; going back to the last confirmed choice
network-profile: applied eth0_role=internet priority=eth,wifi,modem local_address=172.168.1.123/24
```

The unit had its DHCP address again in the same second. When the change is right, confirm it over a link that still works, within the timeout:

```bash
network-profile confirm
```

A reboot before `confirm` also goes back, so a choice that was never confirmed cannot stay in force. To go back by hand, run `network-profile revert`.

## What eth0 does when it is local-only

`network-profile set --confirmed eth0_role=local` generates this file for eth0:

```ini
[Match]
Name=eth0

[Network]
Address=172.168.1.123/24
DHCP=no
LinkLocalAddressing=no
IPv6AcceptRA=no
DNSDefaultRoute=no

[Link]
RequiredForOnline=no
```

No `Gateway=`, no DHCP client and no route metric, so nothing the sensor network offers is applied and eth0 never carries the default route. The unit does not wait for it at boot.

## A USB Ethernet adapter

A USB Ethernet adapter becomes an internet link at the Ethernet metric without naming its interface. `90-network-profile-usb-nic.rules` sets `AVOCADO_USB_NIC=1` on an Ethernet-type link that comes from USB, and clears it for these USB vendors, which are cellular modems: 3838 (Eagle), 2c7c (Quectel), 1bc7 (Telit), 1199 (Sierra Wireless), 05c6, 12d1 (Huawei), 19d2 (ZTE) and 1e0e (Simcom). A modem that shares the adapter's kernel driver (`cdc_ether`, `cdc_ncm`) therefore does not get the adapter's profile. The generated `10-np-usb-ethernet.network` matches `Property=AVOCADO_USB_NIC=1`.

Add a vendor to the list in that rules file when a modem you use is not on it.

## Waiting for the network at boot

`zz-network-profile.conf` makes `systemd-networkd-wait-online` finish as soon as one managed link is up and give up after 30 s. Without `--any`, a Wi-Fi radio that has no network configured counted as a link to wait for: on a unit with eth0 routable, the wait ran to its 30 s timeout. With `--any` the same unit was online in 5 ms.

## What survives a reboot

The choice lives in `/var/lib/network-profile/choice`, the last confirmed one in `last-good`, and a pending trial is the file `unconfirmed`. The networkd files are regenerated into `/run/systemd/network` by `network-profile-apply.service` on every boot, which runs after the extension merge and before the wait for the network.

On a Pi 5 with a confirmed `priority=modem,wifi,eth` and a trial of `priority=wifi,modem,eth` left unconfirmed, a reboot brought back the confirmed choice and dropped the trial, and the journal said so:

```text
network-profile: the unit rebooted before the last change was confirmed; going back to the last confirmed choice
network-profile: applied eth0_role=internet priority=modem,wifi,eth local_address=172.168.1.123/24
```

The default route over eth0 had metric 300 after that boot, and `unconfirmed` was gone. If the stored choice cannot be read, the unit uses the defaults and says why in the journal:

```text
network-profile: the stored choice is not usable, using the defaults:
network-profile:   priority must list eth, wifi and modem once each, comma separated, not 'bogus'
```

## Tests

`tests/test-network-profile.sh` runs the script against a scratch directory (43 checks): the files it generates, the metrics for each priority, the local-only eth0, trial, confirm and revert, a reboot with an unconfirmed change, and refusal of invalid input.
