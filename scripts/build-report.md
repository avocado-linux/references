# Avocado References — Build Check

- **Started:** 2026-07-27 18:08:48 CDT
- **Updated:** 2026-07-28 10:43:53 CDT  _(rewritten after each step while the run is live)_
- **CLI:** `avocado 1.0.0-rc.1` · execution channel: bash
- **Logs:** `/private/tmp/claude-501/-Users-nick-work-repos-avocado/3f890aba-29ea-4ef5-80cb-fc6272753b21/scratchpad/refcheck-final`

Legend: ✅ pass · ❌ fail · ⏳ in progress · … pending · – skipped

| # | Reference | Target | install | build | Result |
|--:|-----------|--------|:-------:|:-----:|--------|
| 1 | astra-1680-deepx | grinn-astra-1680-sbc | ❌ | – | FAIL @ install |
| 2 | c-gpio | raspberrypi5 | ✅ | ✅ | PASS |
| 3 | cpp-tui-dashboard | qemux86-64 | ✅ | ✅ | PASS |
| 4 | dev | qemuarm64 | ✅ | ✅ | PASS |
| 5 | docker-registry | raspberrypi5 | ✅ | ✅ | PASS |
| 6 | docker-save | raspberrypi5 | ✅ | ✅ | PASS |
| 7 | elixir-phoenix | qemuarm64 | ✅ | ✅ | PASS |
| 8 | icam-540 | jetson-orin-nx | ✅ | ✅ | PASS |
| 9 | imx8mp-npu-nnstreamer | ucm-imx8m-plus | ❌ | – | FAIL @ install |
| 10 | imx8mp-npu-pose | ucm-imx8m-plus | ❌ | – | FAIL @ install |
| 11 | iphone-travel-router | raspberrypi5 | ✅ | ✅ | PASS |
| 12 | java-hello | qemuarm64 | ✅ | ✅ | PASS |
| 13 | jetson-trt | jetson-agx-thor | ✅ | ✅ | PASS |
| 14 | linux-custom-kernel | qemux86-64 | ✅ | ❌ | FAIL @ build |
| 15 | nodejs-dashboard | qemux86-64 | ✅ | ✅ | PASS |
| 16 | nvidia-deepstream | jetson-orin-nano-devkit | ✅ | ✅ | PASS |
| 17 | nvidia-gstreamer-yolo | jetson-orin-nano-devkit | ✅ | ✅ | PASS |
| 18 | pi-metrics-exporter | raspberrypi4 | ✅ | ✅ | PASS |
| 19 | python-flask | qemux86-64 | ✅ | ✅ | PASS |
| 20 | python-mqtt | qemux86-64 | ✅ | ✅ | PASS |
| 21 | python-multiversion-uv | qemux86-64 | ✅ | ✅ | PASS |
| 22 | python-whisper | raspberrypi5 | ✅ | ✅ | PASS |
| 23 | python-yolo | raspberrypi5 | ✅ | ✅ | PASS |
| 24 | qemu-quickstart | qemux86-64 | ✅ | ✅ | PASS |
| 25 | react-dashboard | qemux86-64 | ✅ | ✅ | PASS |
| 26 | ros2-ufactory-lite6 | imx8mp-evk | ✅ | ✅ | PASS |
| 27 | rubicon | raspberrypi4 | ✅ | ❌ | FAIL @ build |
| 28 | rust-vitals | qemux86-64 | ✅ | ✅ | PASS |
| 29 | shell-heartbeat | qemux86-64 | ✅ | ✅ | PASS |
| 30 | webkit-ui | raspberrypi5 | ✅ | ✅ | PASS |
| 31 | zephyr-imx8mp-evk | imx8mp-evk | ✅ | ❌ | FAIL @ build |

**Totals:** 25 ✅ passed · 6 ❌ failed · 0 ⏳ pending — 31 total

## Failures

- **astra-1680-deepx** (`grinn-astra-1680-sbc`) — FAIL @ install: `No match for argument: avocado-ext-dev` (extension not published in the feed for this target)
- **imx8mp-npu-nnstreamer** (`ucm-imx8m-plus`) — FAIL @ install: `No match for argument: avocado-ext-dev` (extension not published in the feed for this target)
- **imx8mp-npu-pose** (`ucm-imx8m-plus`) — FAIL @ install: `No match for argument: avocado-ext-dev` (extension not published in the feed for this target)
- **linux-custom-kernel** (`qemux86-64`) — FAIL @ build: `qemu-x86_64-static: Could not open '/lib/ld-linux-x86-64.so.2'` (kernel host tool built for x86_64 can't run when cross-building on an arm64 host)
- **rubicon** (`raspberrypi4`) — FAIL @ build: `ext build avocado-ext-cli failed` (upstream avocado-ext-cli package build)
- **zephyr-imx8mp-evk** (`imx8mp-evk`) — FAIL @ build: `FATAL ERROR: target directory already exists (…/zephyrproject/zephyr)` (non-idempotent west init hit a stale build dir from a prior run)
