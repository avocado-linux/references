# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Elixir Phoenix

This guide walks you through building and running the Elixir Phoenix reference on Avocado OS. The app compiles a Phoenix LiveView application as an OTP release and displays it on-device via the Cog WebKit browser.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

For hardware targets, you will also need:

- Your target device and any required accessories (SD card, USB cable, serial console adapter)
- See the [Support Matrix](https://docs.peridio.com/hardware/support-matrix) for your target's requirements

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference elixir-phoenix elixir-phoenix
cd elixir-phoenix
```

To target specific hardware instead of the default, pass `--target`:

```bash
avocado init --reference elixir-phoenix --target raspberrypi5 elixir-phoenix
cd elixir-phoenix
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs the Elixir/Erlang toolchain (`nativesdk-elixir`, `nativesdk-erlang`, `nativesdk-rebar3`), Node.js (for asset compilation), and the target Erlang runtime (`erlang-erts`).

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `elixir-compile.sh` inside the SDK container, which:

1. Fetches Mix dependencies (`mix deps.get`)
2. Sets up and deploys frontend assets (`mix assets.setup && mix assets.deploy`)
3. Compiles the application (`mix compile`)
4. Builds an OTP release (`mix release --overwrite`)

Then `elixir-install.sh` copies the release from `ref-elixir/_build/prod/rel/ref_elixir/` into the extension sysroot at `/usr/lib/ref-elixir/`.

## Deploy

### QEMU

For QEMU targets, provision and boot the VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

### SD card targets (Raspberry Pi, Seeed reTerminal, NXP, STMicroelectronics)

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the device and apply power.

### USB flash targets (OnLogic)

```bash
avocado provision -r dev --profile usb
```

### NVIDIA Jetson

```bash
avocado provision -r dev --profile tegraflash
```

Follow the USB disconnect/reconnect prompts during the flash process.

## Verify

Log in as `root` with an empty password. The Phoenix app starts automatically on boot and the Cog browser opens to `http://127.0.0.1:4000`.

Check the service is running:

```bash
systemctl status ref-elixir
```

Watch logs:

```bash
journalctl -u ref-elixir -f
```

On hardware targets with a display, the Cog WebKit browser will render the Phoenix LiveView UI on screen. You can also access the app from another machine via `http://<device-ip>:4000`.

## Customize

### Modify the Phoenix app

The Phoenix application source is in the `ref-elixir/` directory. Edit templates, LiveView modules, and routes as you would any standard Phoenix project.

### Change the Cog browser URL

Edit `overlay/etc/default/cog-avocado`:

```
COG_URL=http://127.0.0.1:4000/my-page
```

### Add Mix dependencies

Edit `ref-elixir/mix.exs` to add dependencies, then rebuild:

```elixir
defp deps do
  [
    {:phoenix, "~> 1.7"},
    {:phoenix_live_view, "~> 1.0"},
    {:my_new_dep, "~> 0.1"}
  ]
end
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```

### Reset the build

The SDK container cross-compiles the Phoenix app, and Mix caches artifacts into `ref-elixir/_build/` and `ref-elixir/deps/` between runs. Some of those artifacts are architecture- or ERTS-specific (platform-pinned `esbuild`/`tailwind` binaries, compiled BEAM files, native NIFs). If you switch target architectures, change the SDK container image, or the Erlang/Elixir version bumps, a stale cache can make the Erlang VM crash on boot during compile with something like:

```
Runtime terminating during boot ({load_failed,[lists,filename,erl_parse,ets,...]})
```

That's the symptom of BEAM/ERTS mismatch. Wipe the Mix caches and rebuild:

```bash
avocado ext clean example-elixir -t raspberrypi5
avocado build -t raspberrypi5
```

`avocado ext clean <ext>` walks the extension's compile dependencies and runs the matching `clean:` script — in this reference, that's `elixir-clean.sh`, which removes `_build/`, `deps/`, `assets/node_modules/`, and `priv/static/assets/` from `ref-elixir/`. It resolves the target the same way `avocado build` does, so pass `-t <target>` (or set `AVOCADO_TARGET`) to match the build you're trying to clean.

Note that the top-level `avocado clean` does **not** run this script. It only removes project-level state (the Docker volume, `.avocado-state`, optionally stamps). To run a specific compile section's clean script directly, use:

```bash
avocado sdk clean --section example-elixir-app -t raspberrypi5
```
