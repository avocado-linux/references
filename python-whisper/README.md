---
language: Python
targets:
  - raspberrypi5
  - raspberrypi4
topics:
  - ai
icon: icon.png
---

# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Whisper Speech-to-Text

A reference runtime that runs OpenAI's Whisper speech-to-text model locally on a Raspberry Pi 5 with a USB microphone. The app continuously records audio, transcribes it on-device, and logs structured JSON results to the journal. No cloud API calls required.

- Bundle the Whisper `tiny` model (~75MB) into the image for fully offline inference
- Capture audio from a USB microphone using ALSA
- Run continuous speech-to-text transcription on the Cortex-A76 CPU
- Output structured JSON transcription results to the systemd journal
