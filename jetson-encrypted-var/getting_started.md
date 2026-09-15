# Getting Started with Encrypted /var on Jetson

This reference puts a runtime's `/var` on a LUKS2 volume whose key is sealed to
the Jetson's OP-TEE firmware TPM. The partition is encrypted in place on first
boot, so anything seeded into the image at build time survives the conversion.

Everything below was run end to end on a Jetson Orin Nano, and the outputs are
copied from that run.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview), 1.0.0-rc.3 or newer
- One of: Jetson Orin Nano, Orin NX, AGX Orin, AGX Thor
- A USB-C cable from the Jetson to your host, for flashing
- Roughly 16 GB free disk

This reference requires the **2026** release. `cryptsetup-var` is not published
on 2024 at all, so a 2024 project fails during `avocado install` with an error
that names no missing package. The `distro` block in `avocado.yaml` already
pins `release: 2026` and `channel: next`.

## Initialize

```bash
avocado init --reference jetson-encrypted-var jetson-encrypted-var
cd jetson-encrypted-var
```

## Install

```bash
avocado install -f
```

## Build

```bash
avocado build
```

There are no compile steps in this reference. The build assembles the runtime
from pre-built packages and extensions, and writes the encryption markers into
the initramfs that the initrd reads at boot.

`var` is part of the runtime build stamp, so toggling `encrypt` forces a
rebuild rather than silently reusing the previous image.

## Deploy

Put the board into Force Recovery Mode first:

1. Power off
2. Short `FC REC` to `GND` with a jumper
3. Connect USB-C from the Jetson to your host
4. Apply power

Confirm the host sees it:

```bash
lsusb | grep -i nvidia
# Bus 001 Device 018: ID 0955:7523 NVIDIA Corp. APX
```

Then flash, choosing the profile that matches the storage your board actually
has:

```bash
avocado provision dev --profile tegraflash-mmc
```

| Profile | Writes to |
|---------|-----------|
| `tegraflash` / `tegraflash-nvme` | `nvme0n1` (the default) |
| `tegraflash-mmc` / `tegraflash-emmc` | `mmcblk0` |
| `tegraflash-sd` | `mmcblk1` |

The profile names a device path, not a medium. On an Orin Nano Developer Kit
with no NVMe fitted, the microSD enumerates as `mmcblk0` because there is no
eMMC to take that name, so `tegraflash-mmc` is the right choice there and
`tegraflash-sd` fails with `could not find mmcblk1`.

A successful run ends with `Final status: SUCCESS`. Remove the jumper, replug,
and power on.

## Verify

Log in as `root` with an empty password.

The firmware TPM came up:

```bash
ls -l /dev/tpm*
# crw-rw---- 1 tss  root  10,   224 /dev/tpm0
# crw-rw---- 1 root tss  251, 65536 /dev/tpmrm0
```

`/var` is mounted through the encrypted mapper rather than the raw partition:

```bash
findmnt -no SOURCE,FSTYPE /var
# /dev/mapper/var btrfs
```

The volume is LUKS2 and its key is sealed to PCR 7:

```bash
cryptsetup luksDump /dev/mmcblk0p16
# Version:       2
# Tokens:
#   0: systemd-tpm2
#         tpm2-hash-pcrs:   7
#         tpm2-pcr-bank:    sha256
```

Both keyslots exist, the hardware slot and the fallback:

```bash
avocadoctl var-key list
# device: /dev/mmcblk0p16
# slot 0: passphrase (Argon2id recovery / derived key)
# slot 1: systemd-tpm2
```

Do not look for `/etc/avocado/var-encrypt` or `/etc/avocado/var-hardware` on the
running system. Those markers live in the initramfs for the initrd to read at
boot; they are absent from the booted rootfs and their absence there means
nothing.

## Customize

### Choosing the key engine

`var.hardware` selects which engine binds the volume, and the default is not
what you want in production:

| Value | Behaviour |
|-------|-----------|
| `auto` (default) | Uses whatever the machine ships and probes successfully. If no engine probes, it degrades to Argon2id and reports it. |
| `tpm2` | Binds to the TPM and fails closed when that engine is missing. |
| `caam` | Binds to the NXP CAAM, failing closed the same way. |
| `none` | No hardware keyslot. Requires `recovery`. |

On `auto`, a unit whose firmware TPM did not come up still boots using a
software-derived key. It reports the degrade, but the unit is running and the
volume is no longer hardware-bound. This reference sets `tpm2` so that case is a
failure instead of a silent downgrade.

The value is `tpm2`, not `ftpm`. Writing `ftpm` is the obvious guess and is
rejected when the config parses:

```text
runtimes.dev.var.hardware: 'ftpm' is not one of auto, caam, tpm2, none
```

### Holding your own recovery key

The recovery keyslot a device gets by default is derived from its SoC UID, and
the SoC UID is readable by anything on the device. It will get you back into a
unit whose sealed key stopped working, but it is not a secret.

An operator-held master fixes that and lets the derived slot be retired. Create
it once:

```bash
avocado signing-keys create var-recovery --algorithm hmac-sha256
```

Name it in the runtime's `var` block:

```yaml
    var:
      encrypt: true
      hardware: tpm2
      recovery: var-recovery
```

Nothing derived from the master enters a build. Enrolment happens against a
device that is already running:

```bash
avocado var-key enroll dev --device root@<device-ip>
```

Configuring `recovery` alone does not create the slot - until `enroll` runs,
`avocadoctl var-key list` will not show an `avocado-recovery` token.

To recover a unit later, with the master on your bench and the unit's UID:

```bash
avocado var-key derive dev --uid <soc-uid>
```

Hex by default; `--raw` emits the 32 bytes for `cryptsetup --key-file -`. The
UID is read from `/sys/firmware/devicetree/base/serial-number`, falling back to
`/sys/devices/soc0/serial_number`.

### Watching for silent fallback

A unit whose PCR 7 no longer matches what was sealed still boots, opening on the
recovery keyslot instead. That is deliberate, so a firmware update cannot strand
a device, but it means a unit can stop being hardware-bound without anyone
noticing. A device that still lists a `systemd-tpm2` slot but opened without it
is the case to catch, and the condition is logged:

```text
avocado-posture: /var has a TPM2 keyslot but opened with the Argon2id recovery
key - PCR 7 no longer matches what was sealed
```

On targets that boot through U-Boot the same facts are published into the U-Boot
environment each boot. Jetson has no U-Boot in its boot chain, so that path is a
silent no-op there and `fw_printenv` shows no `avocado_var_*` keys. Use
`avocadoctl var-key list` and the journal on Jetson.

### What this does not give you

PCR 7 records secure-boot state rather than what actually booted. The seal binds
to whether secure boot is enabled and which keys are enrolled; it does not
measure the kernel or initramfs, so it is not an attestation of what booted.

Going back to a plaintext `/var` requires re-provisioning the device.
