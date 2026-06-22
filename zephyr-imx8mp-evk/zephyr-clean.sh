#!/usr/bin/env bash
#
# Discard the Zephyr west workspace + build artifacts. Invoked by
# `avocado sdk clean zephyr`.
#
set -euo pipefail

echo "Cleaning Zephyr build artifacts..."
rm -rf zephyr-m7/build
echo "Clean complete"
