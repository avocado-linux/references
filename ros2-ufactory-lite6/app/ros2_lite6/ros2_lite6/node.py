"""Main entrypoint — ROS 2 node + HTTP API + xArm SDK glue.

Threading model:
  * Main thread: rclpy executor spin (`rclpy.spin`)
  * Background thread: uvicorn serving the FastAPI app
  * Both share an `ArmController`. See arm.py for the locking strategy.
"""

from __future__ import annotations

import os
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

import uvicorn

from .arm import JOINT_NAMES, ArmController
from . import sequences
from .http_api import build_app


JOINT_STATE_HZ = 30.0


class Lite6Node(Node):
    def __init__(self, arm: ArmController) -> None:
        super().__init__("lite6_node")
        self._arm = arm

        # Publish on the standard /joint_states topic so robot_state_publisher
        # can consume it directly for TF broadcasting and RViz visualization.
        self._publisher = self.create_publisher(JointState, "/joint_states", 10)
        self.create_timer(1.0 / JOINT_STATE_HZ, self._publish_joint_state)

        self.get_logger().info(
            f"connected to arm ip={arm.ip} mock={arm.is_mock}"
        )

    def _publish_joint_state(self) -> None:
        s = self._arm.status()
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(JOINT_NAMES)
        # joint_states uses radians; xArm SDK returns degrees.
        msg.position = [angle * 3.14159265358979 / 180.0 for angle in s.joints_deg]
        self._publisher.publish(msg)


def _start_http_server(arm: ArmController) -> threading.Thread:
    app = build_app(arm)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    return thread


def _maybe_autostart(arm: ArmController, logger) -> None:
    autostart = os.environ.get("LITE6_AUTOSTART_SEQUENCE", "false").lower()
    if autostart not in ("1", "true", "yes"):
        logger.info("LITE6_AUTOSTART_SEQUENCE disabled; waiting for HTTP commands")
        return
    logger.info("LITE6_AUTOSTART_SEQUENCE=true; running wave sequence")
    threading.Thread(target=sequences.wave, args=(arm,), daemon=True).start()


def main(args=None) -> None:
    rclpy.init(args=args)

    arm = ArmController()
    try:
        arm.connect()
    except Exception as exc:
        # Don't crash the container on first-boot SDK errors — the HTTP
        # /status endpoint will report `connected: false` and the user can
        # fix LITE6_IP and `systemctl restart container-app`.
        rclpy.logging.get_logger("lite6_node").error(
            f"arm connect failed: {exc!r}"
        )

    _start_http_server(arm)

    node = Lite6Node(arm)
    _maybe_autostart(arm, node.get_logger())

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        arm.disconnect()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
