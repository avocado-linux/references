# Getting Started with KVM ivshmem zero-copy

Build the two-VM zero-copy demo, flash it to a QCS6490 board, and read the
round-trip numbers off the host journal.

## Prerequisites

- Avocado CLI `>=0.41.0` and a container runtime (Docker/Podman).
- A supported board: RB3 Gen 2 Vision Kit (`rb3gen2`, default) or RUBIK Pi 3
  (`rubikpi3`). Both are QCS6490.
- The board flashed with the **KVM** XBL config. Under the stock (Gunyah) config
  Linux runs at EL1, `/dev/kvm` is absent, and `launch-vm` exits — it does not
  fall back to TCG.
- The board's BSP and dev extensions available in your `<target>-ext` feed
  (`avocado-ext-dev`, `avocado-ext-sshd-dev`, `avocado-bsp-<board>`). These live
  in a repo separate from the package feed; against a local feed they must be
  published first (see Install).

## Initialize

Pick the board with `-t`; `default_target` is `rb3gen2`.

```sh
avocado update -t rb3gen2
avocado sdk install --force -t rb3gen2
```

## Install

```sh
avocado ext install --force -t rb3gen2
avocado build -t rb3gen2
```

`ext install` resolves `avocado-ext-dev`, `avocado-ext-sshd-dev` and the board's
BSP extension from the `<target>-ext` repo — a SEPARATE repo from the package
feed, not created by syncing packages. Against a local feed it has to be
populated first, or the step dies with `Unable to find a match:
avocado-ext-dev` after a 404 on `.../target/<target>-ext/repodata/repomd.xml`.
Each extension is its own repo and needs its own install → build → image before
it can be consumed, then publish them with meta-avocado's
`scripts/dev-package-extensions.sh -t rb3gen2`.

`avocado ext fetch` with no NAME fetches **every** extension declared with
`source: { type: package }`, not just the ones the selected target uses. Fetch
by name instead:

```sh
for n in avocado-ext-dev avocado-ext-sshd-dev avocado-bsp-rb3gen2; do
  avocado ext fetch "$n" -t rb3gen2
done
```

### Building against a local feed

If you run a repo server on the host, reach it from the SDK container with
`--network=host` (passed on the command line rather than baked into
`sdk.container_args`, so the committed config never asks for host networking
against the published feed):

```sh
export AVOCADO_REPO_URL=http://localhost:8080
avocado sdk install --force -t rb3gen2 --container-arg=--network=host
avocado ext  install --force -t rb3gen2 --container-arg=--network=host
avocado build              -t rb3gen2 --container-arg=--network=host
```

> Recent avocado-cli builds detect a loopback feed URL and rewrite it to
> `http://host.docker.internal:8080`, supplying their own network argument.
> Passing `--network=host` on top then fails with `network "host" is specified
> multiple times` — drop the flag on those builds. `avocado update` never
> accepted `--container-arg`.

## Build

`avocado build` assembles the rootfs, the runtime (the four extensions in
`depends_on` order), and the ESP. The guest binary is cross-compiled by the SDK
(`guest-compile.sh`, `-static` against `libc6-staticdev`) and packed into the
guest initramfs; `guest-install.sh` stages it and the `avocado-shm.ko` built by
Yocto into the `vmm` sysroot.

## Provision

Flashing goes over QDL with the board in Qualcomm EDL mode:

```sh
avocado provision --profile ufs -t rb3gen2
```

**The `--profile ufs` flag is not optional and nothing infers it.** avocado-cli
does not choose the provisioning script: it runs the SDK's
`avocado-provision-<arch>` hook, which calls `stone provision`, which reads the
profile out of the stone manifest. So the CLI never learns that "ufs" ran, and
the `provision.ufs.container_args` block in `avocado.yaml` — which bind-mounts
`/dev/bus/usb` and adds `--privileged` — is keyed on a name it only gets from
the flag. Without it the block is inert, the container comes up with no usbfs,
and the run prints "QDL device found" (the wait loop reads sysfs, which the
container does have) and then dies in `qdl: failed to initialize libusb`.

The board must enumerate as `05c6:9008` — check with `lsusb` before starting.
`05c6:900e` is NOT EDL; it is the SoC's dload/ramdump mode, where the board
lands after a failed boot. qdl always opens with a Sahara handshake and cannot
skip it, so a 900e board needs a physical power cycle into EDL to return to
9008. Confirm the exact button/jumper against Qualcomm's board documentation.

## Deploy (OTA): the Vision Kit mezzanine

The RB3 Gen 2 is a core kit plus a mezzanine whose hardware is reachable only
once its device-tree overlay is applied. The overlay ships in the mezzanine's
own extension, so naming the board variant decides whether it is built into the
runtime UKI:

| `AVOCADO_TARGET_BOARD` | BSP resolved | Device tree |
|---|---|---|
| unset | `avocado-bsp-rb3gen2` | base only |
| `rb3gen2-vision` | `avocado-bsp-rb3gen2-vision` | base + vision mezzanine |

Nothing in `avocado.yaml` changes between the two: the BSP entry is
`avocado-bsp-{{ avocado.target.board }}`, and the vision extension `depends_on`
the core kit, so naming the variant pulls both in order. Provision on the core
kit, then deploy the variant as an OTA (not a reflash):

```sh
export AVOCADO_TARGET_BOARD=rb3gen2-vision
avocado update      -t rb3gen2
avocado sdk install -t rb3gen2 --force
avocado ext install -t rb3gen2 --force
avocado build       -t rb3gen2
avocado deploy      -t rb3gen2 --device root@<board-ip>
```

Confirm the overlay actually landed on the board (the ISP node is
`isp@acb3000`; there has never been a node called `camss` on this SoC, so a glob
for one proves nothing):

```sh
cat /proc/device-tree/soc@0/isp@acb3000/status   # "disabled" before, "okay" after
```

## Verify

Each guest's serial console goes to the host journal:

```sh
journalctl -u avocado-vm-alpha -f     # the initiator prints the numbers
journalctl -u avocado-vm-beta  -f     # the responder
```

`vm-alpha` reports min/p50/p99/max round-trip and throughput, then sleeps and
runs again, printing which mapping it got (`/dev/avocado-shm` write-back, or the
ivshmem BAR). A round trip is measured entirely on the initiator's own counter:
KVM gives each guest its own `CNTVOFF_EL2`, so `CNTVCT_EL0` in two guests are not
comparable and a one-way number computed by subtracting them would be
confidently wrong.

Read the numbers against the clock: the guest arch counter runs at 19.2 MHz, so
one tick is 52 ns and a short round trip is only four to five ticks. Do not read
meaning into a 52 ns difference between two runs. For a virtualisation-free
baseline, `pingpong.c` runs the same round trip between two host processes.
