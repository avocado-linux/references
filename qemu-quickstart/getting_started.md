# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with QEMU Quickstart (Experimental)

This guide walks you through booting Avocado OS in QEMU with Avocado Connect and Tunnels for remote device management. This is the fastest way to get a running Avocado OS instance with cloud connectivity.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference qemu-quickstart qemu-quickstart
cd qemu-quickstart
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

## Build

Build the runtime image:

```bash
avocado build
```

There are no compile steps — the build assembles the runtime from pre-built packages and extensions.

## Deploy

Provision and boot the QEMU VM:

```bash
avocado provision -r dev
avocado sdk run -iE vm dev
```

To SSH in from another terminal:

```bash
avocado sdk run -iE vm dev --host-fwd "2222-:22"

# From another terminal:
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost
```

## Verify

Log in as `root` with an empty password.

Confirm the system is running:

```bash
uname -a
systemctl status
```

Check Avocado Connect status:

```bash
systemctl status avocado-conn
```

## Customize

### Configure Avocado Connect

Edit `overlay/etc/avocado-conn/config.toml` with your Peridio organization credentials to enable cloud device management and remote tunnels.

### Add application extensions

Edit `avocado.yaml` to add extensions to the runtime:

```yaml
runtimes:
  dev:
    extensions:
      - avocado-ext-dev
      - avocado-ext-sshd-dev
      - avocado-bsp-{{ avocado.target.board }}
      - avocado-ext-connect
      - avocado-ext-tunnels
      - avocado-ext-docker        # add Docker support
      - avocado-ext-cockpit       # add web-based management UI
      - config
```

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev
```
