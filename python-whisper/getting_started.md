# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with Whisper Speech-to-Text

This guide walks you through building and running the Whisper speech-to-text reference on Avocado OS. The app records audio from a USB microphone on a Raspberry Pi 5, transcribes it locally using the Whisper `tiny` model, and logs the results to the journal.

## Prerequisites

- macOS 10.12+ or Linux (Ubuntu 22.04+, Fedora 39+)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- The latest version of the [Avocado CLI](https://docs.peridio.com/guides/avocado-cli/overview)
- Raspberry Pi 5 (or Raspberry Pi 4)
- USB microphone
- SD card

## Initialize

Clone the reference or initialize a new project from it:

```bash
avocado init --reference python-whisper python-whisper
cd python-whisper
```

To use a Raspberry Pi 4 instead:

```bash
avocado init --reference python-whisper --target raspberrypi4 python-whisper
cd python-whisper
```

## Install

Install the SDK toolchain, extension dependencies, and runtime packages:

```bash
avocado install -f
```

This pulls the SDK container image and installs `nativesdk-uv` for pip package compilation.

## Build

Build the extensions and assemble the runtime image:

```bash
avocado build
```

The build step runs `app-compile.sh` inside the SDK container, which uses `uv pip install` to download `openai-whisper`, `numpy`, and `sounddevice`, then downloads the Whisper `tiny` model (~75MB). Then `app-install.sh` copies the packages to `/usr/lib/app/packages/` and the model to `/usr/lib/app/model/` in the extension sysroot.

## Deploy

### SD card

Insert your SD card and provision:

```bash
avocado provision -r dev --profile sd
```

Insert the SD card into the Raspberry Pi, connect the USB microphone, and apply power.

## Verify

SSH into the Pi or connect via serial console. Log in as `root` with an empty password. The app service starts automatically on boot.

Check the service is running:

```bash
systemctl status app
```

Watch transcriptions in real time:

```bash
journalctl -u app -f
```

You should see output like:

```
whisper app starting on avocado-raspberrypi5
  model: tiny (from /usr/lib/app/model)
  record: 5s at 16000Hz
Loading Whisper model...
Model loaded.
Using audio device: plughw:1,0

Recording 5s of audio...
Transcribing...
{"device": "avocado-raspberrypi5", "timestamp": 1711234567, "text": "hello world this is a test", "language": "en", "audio_seconds": 5, "inference_seconds": 3.42}
```

### Test the microphone manually

```bash
arecord -l                                                      # list capture devices
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 5 /tmp/test.wav  # record 5 seconds
aplay /tmp/test.wav                                             # play it back
```

## Customize

### Change the model size

Edit `app/overlay/usr/local/bin/app.py`:

```python
MODEL_SIZE = "base"       # use a larger model for better accuracy
RECORD_SECONDS = 10       # record longer clips
```

Available models:

| Model | Size | RPi 5 Speed (5s audio) | Accuracy |
|-------|------|----------------------|----------|
| `tiny` | 75MB | ~3s | Good for clear speech |
| `base` | 140MB | ~6s | Better accuracy |
| `small` | 460MB | ~20s | Much better accuracy |

### Rebuild after changes

After any change, rebuild and reprovision:

```bash
avocado build
avocado provision -r dev --profile sd
```
