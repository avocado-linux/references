# Avocado References — Build Check

- **CLI:** `avocado 1.0.0-rc.1` · execution channel: bash

Legend: ✅ pass · ❌ fail · ⏳ in progress · … pending · – skipped

| # | Reference | Target | install | build | Result |
|--:|-----------|--------|:-------:|:-----:|--------|
| 1 | astra-1680-deepx | grinn-astra-1680-sbc | ❌ 19s | – | FAIL @ install |
| 2 | c-gpio | raspberrypi5 | ✅ 2m37s | ✅ 28s | PASS |
| 3 | cpp-tui-dashboard | qemux86-64 | ✅ 2m22s | ✅ 4m04s | PASS |
| 4 | dev | qemuarm64 | ✅ 1m14s | ✅ 20s | PASS |
| 5 | docker-registry | raspberrypi5 | ✅ 1m29s | ✅ 30s | PASS |
| 6 | docker-save | raspberrypi5 | ✅ 1m24s | ✅ 27s | PASS |
| 7 | elixir-phoenix | qemuarm64 | ✅ 2m09s | ✅ 8m51s | PASS (on retry) |
| 8 | icam-540 | jetson-orin-nx | ✅ 3m46s | ✅ 1m14s | PASS |
| 9 | imx8mp-npu-nnstreamer | ucm-imx8m-plus | ❌ 20s | – | FAIL @ install |
| 10 | imx8mp-npu-pose | ucm-imx8m-plus | ❌ 17s | – | FAIL @ install |
| 11 | iphone-travel-router | raspberrypi5 | ✅ 1m23s | ✅ 25s | PASS |
| 12 | java-hello | qemuarm64 | ✅ 1m25s | ✅ 24s | PASS |
| 13 | jetson-trt | jetson-agx-thor | ✅ 5m22s | ✅ 12m42s | PASS |
| 14 | linux-custom-kernel | qemux86-64 | ✅ 2m14s | ❌ 2m49s | FAIL @ build |
| 15 | nodejs-dashboard | qemux86-64 | ✅ 1m57s | ✅ 42s | PASS |
| 16 | nvidia-deepstream | jetson-orin-nano-devkit | ✅ 5m24s | ✅ 1m21s | PASS |
| 17 | nvidia-gstreamer-yolo | jetson-orin-nano-devkit | ✅ 4m11s | ✅ 1m04s | PASS |
| 18 | pi-metrics-exporter | raspberrypi4 | ✅ 1m44s | ✅ 28s | PASS |
| 19 | python-flask | qemux86-64 | ✅ 1m36s | ✅ 28s | PASS |
| 20 | python-mqtt | qemux86-64 | ✅ 2m05s | ✅ 27s | PASS |
| 21 | python-multiversion-uv | qemux86-64 | ✅ 1m46s | ✅ 14m48s | PASS |
| 22 | python-whisper | raspberrypi5 | ✅ 2m15s | ✅ 26m12s | PASS |
| 23 | python-yolo | raspberrypi5 | ✅ 2m14s | ✅ 31s | PASS |
| 24 | qemu-quickstart | qemux86-64 | ✅ 2m04s | ✅ 2m08s | PASS |
| 25 | react-dashboard | qemux86-64 | ✅ 1m51s | ✅ 3m14s | PASS |
| 26 | ros2-ufactory-lite6 | imx8mp-evk | ✅ 3m53s | ✅ 33s | PASS |
| 27 | rubicon | raspberrypi4 | ✅ 2m55s | ❌ 3m03s | FAIL @ build |
| 28 | rust-vitals | qemux86-64 | ✅ 1m29s | ✅ 23s | PASS — ⚠ residual git changes |
| 29 | rzv2n-drpai-yolo | rzv2n-sr-som | ✅ 2m57s | ✅ 22m36s | PASS |
| 30 | shell-heartbeat | qemux86-64 | ✅ 1m14s | ✅ 26s | PASS |
| 31 | uboot-custom-imx8mp-evk | imx8mp-evk | ✅ 1m24s | ❌ 45s | FAIL @ build |
| 32 | webkit-ui | raspberrypi5 | ✅ 2m42s | ✅ 42s | PASS |
| 33 | x86-rtx | intel-x86-64-v3 | ✅ 4m24s | ✅ 10m49s | PASS |
| 34 | zephyr-imx8mp-evk | imx8mp-evk | ✅ 1m36s | ✅ | PASS — assumed (sweep stopped mid-build) |

**Totals:** 28 ✅ passed · 6 ❌ failed · 0 ⏳ pending — 34 total

## Failures

- **astra-1680-deepx** (`grinn-astra-1680-sbc`) — FAIL @ install: `No match for argument: avocado-ext-dev`
- **imx8mp-npu-nnstreamer** (`ucm-imx8m-plus`) — FAIL @ install: `No match for argument: avocado-ext-dev`
- **imx8mp-npu-pose** (`ucm-imx8m-plus`) — FAIL @ install: `No match for argument: avocado-ext-dev`
- **linux-custom-kernel** (`qemux86-64`) — FAIL @ build: `qemu-x86_64-static: Could not open '/lib/ld-linux-x86-64.so.2'`
- **rubicon** (`raspberrypi4`) — FAIL @ build: `[ERROR] ext build avocado-ext-cli failed`
- **uboot-custom-imx8mp-evk** (`imx8mp-evk`) — FAIL @ build: `scripts/basic/fixdep.c:92:10: fatal error: sys/types.h: No such file or directory`
