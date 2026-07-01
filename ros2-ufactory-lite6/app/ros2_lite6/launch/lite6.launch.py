"""ROS 2 launch file for the Lite 6 controller.

Brings up:
  1. robot_state_publisher — reads the URDF and subscribes to /joint_states
     to broadcast TF transforms for every link. This is what makes the arm
     visible in RViz on any machine on the same DDS domain.

  2. lite6_node — the arm driver that publishes /joint_states at 30 Hz and
     serves the HTTP control API on port 8080.

  3. foxglove_bridge — WebSocket server on port 8765 that exposes all ROS 2
     topics to Foxglove Studio for browser-based visualization. Open
     https://app.foxglove.dev and connect to ws://<device-ip>:8765.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("ros2_lite6")
    urdf_path = os.path.join(pkg_share, "urdf", "lite6.urdf")

    with open(urdf_path, "r") as f:
        robot_description = f.read()

    return LaunchDescription([
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
            output="screen",
        ),
        Node(
            package="ros2_lite6",
            executable="node",
            name="lite6_node",
            output="screen",
        ),
        Node(
            package="foxglove_bridge",
            executable="foxglove_bridge",
            name="foxglove_bridge",
            parameters=[{
                "port": 8765,
                "address": "0.0.0.0",
                "send_buffer_limit": 10000000,
                "topic_whitelist": [".*"],
            }],
            output="screen",
        ),
    ])
