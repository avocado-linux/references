#!/usr/bin/env python3

import sys
sys.path.insert(0, "/usr/lib/app/packages")

import json
import time
import os
import tempfile
import subprocess
import numpy as np
import whisper

MODEL_DIR = "/usr/lib/app/model"
MODEL_SIZE = "tiny"
RECORD_SECONDS = 5
SAMPLE_RATE = 16000
DEVICE_ID = os.uname().nodename

def find_usb_mic():
    """Find the ALSA device name for the USB microphone."""
    try:
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "card" in line.lower() and "usb" in line.lower():
                parts = line.split(":")
                card = parts[0].split()[-1]
                return f"plughw:{card},0"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "plughw:1,0"

def record_audio(device, seconds, sample_rate):
    """Record audio from ALSA device, return as numpy float32 array."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name

    try:
        subprocess.run(
            [
                "arecord",
                "-D", device,
                "-f", "S16_LE",
                "-r", str(sample_rate),
                "-c", "1",
                "-d", str(seconds),
                "-t", "wav",
                tmp_path,
            ],
            capture_output=True, timeout=seconds + 5
        )
        audio = whisper.load_audio(tmp_path)
        return audio
    finally:
        os.unlink(tmp_path)

def main():
    print(f"whisper app starting on {DEVICE_ID}", flush=True)
    print(f"  model: {MODEL_SIZE} (from {MODEL_DIR})", flush=True)
    print(f"  record: {RECORD_SECONDS}s at {SAMPLE_RATE}Hz", flush=True)

    # Load model
    print("Loading Whisper model...", flush=True)
    model = whisper.load_model(MODEL_SIZE, download_root=MODEL_DIR)
    print("Model loaded.", flush=True)

    # Find USB mic
    mic_device = find_usb_mic()
    print(f"Using audio device: {mic_device}", flush=True)

    while True:
        print(f"\nRecording {RECORD_SECONDS}s of audio...", flush=True)
        try:
            audio = record_audio(mic_device, RECORD_SECONDS, SAMPLE_RATE)
        except Exception as e:
            print(f"Recording failed: {e}", flush=True)
            time.sleep(5)
            continue

        print("Transcribing...", flush=True)
        start = time.time()
        result = model.transcribe(audio, fp16=False)
        elapsed = time.time() - start

        text = result["text"].strip()
        language = result.get("language", "unknown")

        output = {
            "device": DEVICE_ID,
            "timestamp": int(time.time()),
            "text": text,
            "language": language,
            "audio_seconds": RECORD_SECONDS,
            "inference_seconds": round(elapsed, 2),
        }

        print(json.dumps(output), flush=True)

        time.sleep(1)

if __name__ == "__main__":
    main()
