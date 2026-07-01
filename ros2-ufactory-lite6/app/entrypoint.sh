#!/usr/bin/env bash
set -e

# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source /ws/install/setup.bash

exec ros2 launch ros2_lite6 lite6.launch.py
