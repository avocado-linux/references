# Getting Started with Jetson Orin Nano Power Management

This guide builds the power-managed runtime for a Jetson Orin Nano 8GB devkit, flashes it, gets a shell on the board, and
measures idle power.

## Prerequisites

- A Linux host: flashing a Jetson in recovery mode needs direct USB access to the board (macOS and Windows are untested)
- [Docker](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A Jetson Orin Nano 8GB devkit, a USB-C cable to the host, a jumper wire for the FC_REC pin, and a USB serial adapter for
  the debug console
- An SD card or an NVMe drive in the board for the OS

## Initialize

```bash
avocado init --reference jetson-orin-nano-power jetson-orin-nano-power
cd jetson-orin-nano-power
```

## Install and build

```bash
avocado install -f
avocado build
```

`avocado install` pulls the SDK and the four extensions from the package feed. `avocado build` assembles the runtime
`power`. There is no compile step.

## Provision

Put the board in USB recovery mode: connect FC_REC to GND, attach the USB-C cable to the host, and power-cycle the board.
Check that the host sees it:

```bash
lsusb -d 0955:7523
```

Expected: one line, `ID 0955:7523 NVIDIA Corp. APX`. Then provision. For the NVMe:

```bash
avocado provision -r power --profile tegraflash-nvme
```

For an SD card in the board's slot, use `--profile tegraflash-sd`. Both erase the target entirely and rewrite the QSPI
firmware and the UEFI variables. When it finishes, remove the FC_REC jumper and power-cycle the board.

If provision cannot flash the board from its container on your host (the CLI reports that it could not retrieve the chip
ID), flash from the host instead. This reference does not cover that path.

## Get a shell

A fresh board has no credentials: root is locked. The `avocado-ext-bringup` extension logs the serial console in as root, so
open the debug console (115200 baud) and you land at a root prompt. Put your public key where `avocado-ext-sshd-dev` reads it:

```bash
mkdir -p /var/lib/ssh
echo 'ssh-ed25519 AAAA... you@host' >> /var/lib/ssh/authorized_keys
ip -brief address
```

Then from the host:

```bash
ssh root@<device-ip>
```

## Verify

On the device, check the extensions and the power units:

```bash
avocadoctl status
systemctl is-active nvpower.service nvpmodel.service avocado-idle-governors.service
```

Then measure idle power from the host (it waits until the board has been up for 240 s, then samples for 90 s):

```bash
ssh root@<device-ip> sh -s < verify-power.sh
```

On the bench board, two boots read an idle VDD_IN mean of 4717 mW and 4747 mW with the 25 W mode, `simple_ondemand` on the GPU
and `schedutil` on the CPUs. Your reading depends on the carrier board and what is attached to it.

## Development Mode

The serial autologin in `avocado-ext-bringup` gives a root shell to anyone with access to the console. Remove the extension
from `runtimes.power.extensions` in `avocado.yaml` before shipping.
