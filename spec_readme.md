# README.md Specification

The README serves two purposes: it provides structured metadata via YAML frontmatter for the docs build system, and a brief human-readable summary of the reference.

## Frontmatter

The README **must** begin with YAML frontmatter containing the following fields:

```yaml
---
language: Python
targets:
  - "*"
topics:
  - mqtt
  - telemetry
icon: icon.png
---
```

### Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `language` | yes | string | The primary programming language. Use the canonical name with standard capitalization (e.g., `Python`, `Rust`, `C`, `Java`, `Elixir`, `JavaScript`, `React`). |
| `targets` | yes | string or list | One or more supported target identifiers from the [Support Matrix](https://docs.peridio.com/hardware/support-matrix). Use `"*"` to indicate all targets are supported. When listing specific targets, use the exact target identifier (e.g., `raspberrypi5`, `jetson-orin-nano-devkit`). |
| `topics` | yes | list | One or more topic tags describing what the reference demonstrates. Use lowercase, hyphenated values. Examples: `mqtt`, `telemetry`, `vision`, `gpio`, `cross-compilation`, `ui`, `camera`, `gstreamer`. |
| `icon` | no | string | Filename of an icon image in the same directory as the README. Must be a PNG or SVG file committed to the repo. No URLs. If omitted, a default icon is used. |

### Valid target identifiers

The following target identifiers are recognized. Use these exact strings in the `targets` field:

| Target | Hardware |
|--------|----------|
| `*` | All supported targets |
| `icam-540` | Advantech ICAM-540 |
| `intel-x86-64-v2` | Intel x86-64-v2 |
| `intel-x86-64-v3` | Intel x86-64-v3 |
| `jetson-agx-orin-devkit` | NVIDIA Jetson AGX Orin Developer Kit |
| `jetson-orin-nano-devkit` | NVIDIA Jetson Orin Nano Developer Kit |
| `imx91-frdm` | NXP FRDM i.MX 91 |
| `imx8mp-evk` | NXP i.MX 8MP EVK |
| `imx93-evk` | NXP i.MX 93 EVK |
| `imx93-frdm` | NXP i.MX 93 FRDM SBC |
| `fr201` | OnLogic FR201 |
| `raspberrypi4` | Raspberry Pi 4 Model B |
| `raspberrypi5` | Raspberry Pi 5 |
| `raspberrypi0-2w` | Raspberry Pi Zero 2 W |
| `reterminal` | Seeed reTerminal |
| `reterminal-dm` | Seeed reTerminal DM |
| `stm32mp257f-dk` | STMicroelectronics STM32MP257F-DK |
| `qemuarm64` | QEMU ARM |
| `qemux86-64` | QEMU x86-64 |

## Body

After the frontmatter, the README body should be concise. It contains:

1. **Title** — An `H1` heading with the reference name. If an icon is specified in the frontmatter, render it inline with the title at 32x32:
   ```markdown
   # <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Python MQTT Telemetry
   ```
2. **Summary** — One or two sentences describing what the reference does and what it demonstrates.
3. **Highlights** (optional) — A short bullet list of key concepts the reference covers.

The README should **not** contain build instructions, detailed explanations, or getting started steps. That content belongs in `getting_started.md`.

## Validation

The docs build system parses each reference and validates:

1. `README.md` exists and contains valid YAML frontmatter
2. `language` is a non-empty string
3. `targets` is either `"*"` or a list of valid target identifiers
4. `topics` is a non-empty list of strings
5. `getting_started.md` exists
6. If `icon` is specified, the file exists in the reference directory
