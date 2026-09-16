---
language: C
targets:
  - rb3gen2
  - rubikpi3
topics:
  - kvm
  - virtualization
  - shared-memory
  - real-time
  - cross-compilation
  - kernel-module
---

# KVM ivshmem zero-copy

Two Linux VMs under KVM passing data between themselves through one region of
host memory that both guests map directly — no copies, no host relay, no syscall
on the data path after the initial `mmap`. The host runs the PREEMPT_RT kernel,
so the guests are where anything that would perturb RT latency belongs.

Runs on QCS6490 boards — the Qualcomm RB3 Gen 2 Vision Kit and the RUBIK Pi 3.
The board-specific part — which cores the guests are pinned to — is one
directory under `cpus/`, selected by `overlay: cpus/{{ avocado.target }}`, so
adding a board is adding a directory, not a second copy of the VMM. Highlights:

- **An extension per VM, over a shared platform.** A `class: platform` extension
  (`vmm`) carries qemu, the guest kernel and the guest initramfs exactly once;
  two `class: application` extensions (`vm-alpha`, `vm-beta`) `depends_on` it and
  carry only their own identity — a role, a memory size, a CPU set. A third VM is
  another ~20 lines, not another qemu.
- **Zero-copy transport that is cacheable.** Both qemu processes are handed the
  same `memory-backend-file`, so the identical host pages appear in both guests
  and are written and read in place. The pages are claimed as write-back
  cacheable RAM (see below), not as an uncached PCI BAR — the single biggest
  lever on latency in the whole reference.
- **Selecting the RT kernel from a two-kernel feed.** The QCS6490 2026 feed
  carries stock and PREEMPT_RT kernels off one source tree, told apart by
  `CONFIG_LOCALVERSION`; `kernel.version: "6.18.37-rt*"` picks the RT one (the
  resolver's glob is prefix-only — read the note in `avocado.yaml` before
  changing it).
- **Both `depends_on` spellings**, the OTA device-tree path for the Vision Kit's
  mezzanine, and the QDL/EDL provisioning flow — all exercised.

## What it demonstrates

**Extensions per VM, with a shared platform underneath.** The interesting part
of this reference is its shape:

```
              vmm            class: platform
             ^   ^           qemu-system-aarch64, the launcher, the guest initramfs
  depends_on |   | depends_on
        vm-alpha  vm-beta    class: application
                             one env file and one unit each
```

Everything heavy lives once in `vmm`. `avocado ext install` expands the
`depends_on` closure and installs dependencies first, so `vmm`'s sysroot is
fully populated before either VM extension is built from it. Both `depends_on`
spellings appear on purpose: `vm-alpha` uses the constrained form
(`{name: vmm, version: "^0.1.0"}`), `vm-beta` the plain string.

**Zero-copy transport, and it has to be cacheable.** *How* the shared pages get
mapped matters more than anything else here. The obvious route is
`ivshmem-plain`, which presents the region as a PCI BAR; the guest maps BAR2
through sysfs. That works, and it is slow: on arm64 a PCI resource mmap is
`Device-nGnRE`, uncached and un-prefetched, so a polling loop pays an
interconnect round trip per read.

So the region is instead handed to the guests as plain RAM — a second cold
`-numa` node backed by the same `memory-backend-file` — and claimed inside the
guest by `guest-mod/avocado-shm.c`, a small out-of-tree platform driver that
finds it through a `reserved-memory` node and hands it out via `mmap` on
`/dev/avocado-shm`. The entire point is what it does *not* do:

```c
/* No pgprot_noncached()/pgprot_writecombine() -- the default is what
 * makes the mapping cacheable, which is the point. */
return remap_pfn_range(vma, vma->vm_start,
                       (shm_base + off) >> PAGE_SHIFT,
                       len, vma->vm_page_prot);
```

The `reserved-memory` node deliberately omits `no-map`, which is what keeps the
pages in the kernel's linear map so `remap_pfn_range` maps them write-back
cacheable. With `no-map` the pages leave the linear map, `pfn_is_map_memory()`
goes false, and the mapping silently degrades to uncached — the exact behaviour
the driver exists to avoid. The demo prefers `/dev/avocado-shm` and falls back
to the BAR, printing which one it got, so both paths stay exercised.

Across development bring-up the cacheable path measured roughly a **12× latency
and 7.5× throughput** improvement over the BAR on the same board, same payload,
same handshake — an architectural difference (write-back vs `Device-nGnRE`), not
a tuning one. Re-measure on your own board before quoting absolute numbers.

**Selecting the RT kernel.** `kernel.version` picks the RT kernel from the
two-kernel feed; see the note in `avocado.yaml` and read it before changing that
string — the resolver's glob is prefix-only and `"*rt*"` does not do what it
looks like.

## Layout

| Path | What it is |
|------|-----------|
| `avocado.yaml` | Runtime, the four extensions, the kernel pin, the SDK |
| `guest/shmdemo.c` | The guests' PID 1: maps the region and runs the round trip |
| `guest-mod/avocado-shm.c` | Out-of-tree driver that maps the region cacheable |
| `guest-dt/avocado-shm.dtso` | Overlay declaring the `reserved-memory` node |
| `cpus/<target>/` | Which host cores each guest is pinned to, per board |
| `guest-compile.sh` | Cross-compiles with the SDK's `$CC`, packs the initramfs |
| `guest-install.sh` | Stages the initramfs into the `vmm` sysroot |
| `vmm/overlay/` | `launch-vm`, and the ivshmem path/size both VMs share |
| `vm-alpha/`, `vm-beta/` | One `.env` and one unit each |
| `pingpong.c` | Bare-metal host baseline for the same round trip |

See [`getting_started.md`](getting_started.md) to build, provision and run it.

## Status

Booted and running on RB3 Gen 2 (QCS6490) hardware: PREEMPT_RT host, `/dev/kvm`
present, and both guest VMs active under `-cpu host -accel kvm`. The RUBIK Pi 3
target shares the SoC and core layout. KVM needs the board flashed with the KVM
XBL config — under the stock (Gunyah) config Linux runs at EL1, `/dev/kvm` is
absent, and `launch-vm` exits rather than falling back to TCG.

## The RT kernel has no legacy iptables

PREEMPT_RT drops the `ip_tables` compat layer, so the RT kernel ships without the
`iptable-*`/`ip6table-*`/`arptable-*` modules. Nothing in this reference uses
them and the guests have no networking. It matters if you add containers to this
runtime: docker, podman and k3s all want the legacy modules, so they will fail
to install against an RT pin. Use nftables, or run the container workload in one
of the VMs — which is the argument this reference is making anyway.

## Not for production

The `dev` permissions profile sets an empty root password. The guests run
without networking, without a disk, and busy-poll a shared word by design.
