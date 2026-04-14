#!/usr/bin/env bash

set -e

echo "Installing Node.js dependencies..."
cd app
npm install --omit=dev
echo "Node.js dependencies installed successfully"
