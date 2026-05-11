# Getting Started with Jetson GPU Toolbox

This guide boots an Avocado OS development runtime on a Jetson Orin target and walks through validating the iGPU end-to-end. The runtime ships CUDA, cuDNN, TensorRT, DeepStream, the NVIDIA container runtime, the L4T runtime services, the `vectorAdd` smoke test, and the cloud connect agent.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+) workstation
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- A supported Jetson Orin target:
    - NVIDIA Jetson Orin Nano Developer Kit (default)
    - NVIDIA Jetson AGX Orin Developer Kit
    - Advantech ICAM-540 (Orin NX SoM on iCAM-540 carrier)
- USB-C cable for serial-download flashing
- Network connection to the device (Ethernet or Wi-Fi)
- (Optional) A Peridio account if you want the connect agent to register the device. Otherwise the runtime still builds; the agent just won't authenticate.

## Initialize

```bash
avocado init --reference jetson-gpu-toolbox jetson-gpu-toolbox
cd jetson-gpu-toolbox
```

If you're targeting a different Jetson Orin variant, edit `avocado.yaml` and change `default_target` (it must be one of the entries in `supported_targets`).

If you have Peridio credentials, export them so they are baked into the connect block at build time:

```bash
export PERIDIO_ORG_ID=<your-org-uuid>
export PERIDIO_PROJECT_ID=<your-project-uuid>
export PERIDIO_SERVER_KEY=<your-server-key>
```

Skip this if you don't — the build will fall back to placeholders and the connect agent simply won't register.

## Install

```bash
avocado install -f
```

This pulls the SDK toolchain, the BSP extension for the selected target, and the package set for every extension declared in the `dev` runtime: `gpu-toolbox` (the L4T CUDA stack + diagnostic tools), `gpu-test` (vectorAdd source/build deps), `nvidia-docker`, `avocado-ext-connect`, dev shell, and ssh server.

## Build

```bash
avocado build
```

Two things happen here:

1. **`gpu-test` is cross-compiled in the SDK.** The SDK's `nativesdk-cuda-nvcc` host package and `cuda-cudart-dev` target package combine to produce an `aarch64` `vectorAdd` binary linked against `libcudart.so.12`. RPATH is baked in so the loader finds the library at `/usr/local/cuda-*/lib` on the device without an `ld.so.conf.d` drop-in.
2. **Extensions are assembled into sysexts/confexts.** Each one becomes a signed image that the device merges at boot.

## Deploy

```bash
avocado provision -r dev --profile usb
```

For dev kits, put the device in Force Recovery before running the command (hold **Force Recovery** while pulsing **Reset**). After flashing completes, the device reboots into Avocado OS. SSH in as `root` (empty password):

```bash
ssh root@<device-ip-or-mdns-hostname>
```

## Verify

Run these checks from a root shell on the device. Each step builds on the previous — if one fails, fix that before moving on.

### 1. L4T runtime services are up

```bash
systemctl is-active nvstartup.service nvphs.service nv_nvsciipc_init.service
```

All three should print `active`. If any is `inactive` or `failed`, libcuda will fail at `cuInit()` with `CUDA_ERROR_NOT_SUPPORTED` (801) — the kernel module probes successfully but the SoC-side resource manager (NvSciIpc) never gets initialized, and libcuda bails before issuing any nvgpu ioctl. The L4T runtime services and the udev rule that chmods `/dev/nvsciipc` to 0666 are the most common gap when bringing CUDA up on a non-stock-L4T distro.

### 2. Device nodes have the expected permissions

```bash
ls -l /dev/nvsciipc /dev/nvgpu/igpu0/ctrl /dev/nvmap
```

`/dev/nvsciipc` should be `crw-rw-rw-` (0666). If it's `crw-------` (0600) the `61-nvsciipc.rules` udev rule didn't fire — check `udevadm test /sys/devices/platform/...`.

### 3. CUDA works at the driver level

The cleanest pre-flight: call `cuInit` directly via ctypes, no PyTorch needed.

```bash
python3 -c "
import ctypes
cu = ctypes.CDLL('libcuda.so.1')
n = ctypes.c_int(); d = ctypes.c_int(); name = ctypes.create_string_buffer(256)
print('cuInit:           ', cu.cuInit(0))
print('cuDeviceGetCount: ', cu.cuDeviceGetCount(ctypes.byref(n)), '-> count =', n.value)
print('cuDeviceGet:      ', cu.cuDeviceGet(ctypes.byref(d), 0))
print('cuDeviceGetName:  ', cu.cuDeviceGetName(name, 256, d), '->', name.value.decode(errors='replace'))
"
```

Expected: every return code is `0`, count is `1`, name is something like `Orin`.

### 4. End-to-end smoke test (host, not container)

```bash
# Watch GPU load in one shell
tegrastats --interval 500
```

In another shell:

```bash
/usr/local/bin/vectorAdd
```

Default args (16M float elements, 1000 iterations) take a few seconds. While it runs, the `tegrastats` window should show `GR3D_FREQ` jump from ~0% to near 100%. Output ends with `Result: PASS` and exit code 0.

### 5. End-to-end smoke test (in a container)

The runtime ships `nvidia-container-toolkit` but does **not** pre-cache any reference images. Pull whatever you want when you need it:

```bash
# JetPack 6.2 PyTorch container
docker pull nvcr.io/nvidia/l4t-pytorch:r36.4.0-pth2.5-py3

# Same matmul, but inside a container
docker run --rm --runtime nvidia --network host \
    nvcr.io/nvidia/l4t-pytorch:r36.4.0-pth2.5-py3 \
    python3 -c "
import torch
print('cuda:', torch.cuda.is_available(), torch.cuda.get_device_name(0))
x = torch.randn(4096, 4096, device='cuda')
y = x @ x
torch.cuda.synchronize()
print('matmul ok, sum=', y.sum().item())
"
```

For raw CUDA toolchain only (no PyTorch), the smaller base image is `nvcr.io/nvidia/l4t-jetpack:r36.4.0`.

If `--runtime nvidia` is not recognized, check `/etc/docker/daemon.json` for the `nvidia` runtime entry and `systemctl status nvidia-container-setup.service` (it stages the host-files CSV at boot — without it, the runtime can't find libcuda to inject into the container).

### 6. Camera + GPU pipeline (CSI-camera targets only — e.g. ICAM-540)

```bash
gst-launch-1.0 -v nvarguscamerasrc num-buffers=30 ! \
    'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! \
    nvvidconv ! nvjpegenc ! multifilesink location=/tmp/frame_%03d.jpg
```

If you see `tegra-camrtc-capture-vi: uncorr_err: request timed out` in `dmesg`, capture is broken at the sensor / serdes / DT-mode level — not GPU.

## Customize

### Add or remove packages

Edit the relevant extension's `packages:` list in `avocado.yaml`. Common additions to `gpu-toolbox`:

```yaml
gpu-toolbox:
  packages:
    deepstream-7.1-pyds-samples: "*"   # DeepStream Python sample apps
    opencv: "*"                        # OpenCV with NVMM support
    python3-pip: "*"                   # Layer additional Python deps at runtime
    cuda-cudart-dev: "*"               # CUDA headers for on-device builds
```

### Add another Jetson target

Add the target identifier (`jetson-orin-nano-devkit`, `jetson-agx-orin-devkit`, `icam-540`) to `supported_targets`. The BSP extension reference (`avocado-bsp-{{ avocado.target.board }}`) is templated, so it picks up the right BSP automatically.

### Pin the alt-mc 5.15 kernel instead

The Jetson family ships a multi-kernel feed (linux-yocto 6.6 + linux-jammy-nvidia-tegra 5.15). Switch the runtime to 5.15 by changing the `kernel.version` pin:

```yaml
kernel:
  version: "5.15*"
```

The 5.15 kernel is NVIDIA's L4T reference kernel and is the version the JetPack r36.5.0 userspace was tested against. Use it if a 6.6-side regression is suspected during bring-up.

### Compile on-device extras

If you have additional CUDA source to ship as a compiled extension, follow the `gpu-test/` pattern:

```yaml
extensions:
  my-cuda-app:
    types: [sysext]
    version: "0.1.0"
    packages:
      my-cuda-app:
        compile: my-cuda-app
        install: my-cuda-app/install.sh

sdk:
  compile:
    my-cuda-app:
      compile: my-cuda-app/build.sh
      packages:
        cuda-cudart-dev: "*"
```

### Rebuild after changes

```bash
avocado build
avocado provision -r dev --profile usb
```
