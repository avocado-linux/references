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
avocado build -r power
```

`avocado install` pulls the SDK and the extensions from the package feed. `avocado build -r power` assembles the runtime
`power`; without `-r` the CLI builds every runtime, including `trt`. There is no compile step.

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
firmware and the UEFI variables. When it finishes, the board boots the flashed image by itself with the jumper still
fitted, and you do not need to power-cycle it. On the NVMe it reached the root login on the serial console 38 seconds after
the flash ended. Remove the FC_REC jumper before the first power cycle: with it fitted, a power cycle puts the board back
into recovery mode and `lsusb` shows `0955:7523` again.

The `sdk:` block in `avocado.yaml` carries `container_args` with `--privileged`, `-v /dev:/dev` and `-v /sys:/sys`. The
provision container needs them to reach the board over USB. Without them the flash stops at its first step with `could not
retrieve chip ID`, because the container has no `/dev/bus/usb`.

## Get a shell

The `dev` permissions profile in `avocado.yaml` gives `root` an empty password. Log in as `root` on the debug console
(115200 baud), or find the board's address on the console and connect over SSH through `avocado-ext-sshd-dev`:

```bash
ip -brief address
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

## Run a model with TensorRT

The `trt` runtime is the `power` runtime plus the `avocado-ext-trt` extension. Build and flash it the same way, with `-r trt`:

```bash
avocado build -r trt
avocado provision -r trt --profile tegraflash-nvme
```

On the board, build an engine from an ONNX model and run it:

```bash
/usr/src/tensorrt/bin/trtexec --onnx=model.onnx --saveEngine=model.plan --fp16
/usr/src/tensorrt/bin/trtexec --loadEngine=model.plan --duration=60 --warmUp=1000
```

The root filesystem is read-only, so keep models and engines under `/var`, for example `/var/trt`. Run `sync` after
building an engine and before you power-cycle the board: on the bench an engine written just before a power cycle came back
as a 0-byte file, and `trtexec` failed with `read 0 out of 32 bytes`. The cause was not isolated.

## Development Mode

The `dev` permissions profile sets an empty root password, so anyone with the console or network access has a root shell.
Replace it with a profile that has real users and hashed passwords, and point `rootfs` and `initramfs` at it, before
shipping.
