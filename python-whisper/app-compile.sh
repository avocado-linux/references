#!/usr/bin/env bash

set -e

echo "Installing Python dependencies for Whisper..."
uv pip install --target app/packages --python $(which python3) \
  openai-whisper \
  sounddevice \
  numpy

echo "Downloading Whisper tiny model..."
mkdir -p app/model
python3 -c "
import sys
sys.path.insert(0, 'app/packages')
import whisper
whisper.load_model('tiny', download_root='app/model')
print('Model downloaded successfully')
"

echo "Dependencies installed successfully"
