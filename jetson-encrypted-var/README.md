---
language: Shell
targets:
  - jetson-orin-nano
  - jetson-orin-nx
  - jetson-agx-orin
  - jetson-agx-thor
topics:
  - security
  - encryption
  - tpm
  - luks
---

# Encrypted /var on Jetson

A minimal runtime that puts `/var` on a LUKS2 volume whose key is sealed to the
Jetson's OP-TEE firmware TPM. No application code - the point of this reference
is the `var` block in `avocado.yaml`.

- `/var` encrypted in place on first boot, so content seeded at build time survives
- Volume key sealed to the firmware TPM against PCR 7, not stored on disk
- Fails closed: `hardware: tpm2` refuses to fall back to a software-derived key
- A recovery keyslot alongside it, so a firmware update cannot strand a device
- Optional operator-held recovery key via `avocado var-key`

Verified end to end on a Jetson Orin Nano: built with the CLI, flashed, booted,
and confirmed on the device.

## Requires the 2026 release

`cryptsetup-var` is published on the 2026 release only. A project on 2024 fails
during `avocado install` with an error that names no missing package, which is
the first thing to check if the install dies right after the SDK step.
