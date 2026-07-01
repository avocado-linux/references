"""Thin wrapper around the xArm Python SDK with a thread-safe surface and a
mock fallback.

The reference runs in two modes:
  * Live  — LITE6_IP set to a reachable Lite 6 control box.
  * Mock  — LITE6_IP=mock, no SDK call, synthetic joint state. Lets people
            evaluate the rest of the stack without hardware.

Source for the SDK methods called below:
  https://github.com/xArm-Developer/xArm-Python-SDK
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# Lite 6 joint name convention, mirroring xarm_ros2 / URDF.
JOINT_NAMES = [
    "joint1",
    "joint2",
    "joint3",
    "joint4",
    "joint5",
    "joint6",
]

# Home pose (degrees, joint space). Conservative — joint angles all zero.
HOME_JOINTS_DEG = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# Gripper state values reported in status().
GRIPPER_UNKNOWN = "unknown"
GRIPPER_OPEN = "open"
GRIPPER_CLOSED = "closed"
GRIPPER_STOPPED = "stopped"


@dataclass
class ArmStatus:
    connected: bool
    mock: bool
    robot_mode: int
    state: int
    error_code: int
    warn_code: int
    gripper: str
    joints_deg: list[float] = field(default_factory=lambda: [0.0] * 6)
    pose: dict[str, float] = field(default_factory=dict)


class ArmController:
    """Thread-safe facade over xArm SDK. All public methods take the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ip = os.environ.get("LITE6_IP", "192.168.1.117")
        self._mock = self._ip.lower() == "mock"
        self._arm = None  # XArmAPI instance once connected
        self._mock_t0 = time.monotonic()
        self._connected = False
        self._gripper_state = GRIPPER_UNKNOWN

    # ------------------------------------------------------------------
    # Lifecycle

    def connect(self) -> None:
        with self._lock:
            if self._connected:
                return
            if self._mock:
                self._connected = True
                return
            # Lazy import so mock mode doesn't drag in the SDK.
            from xarm.wrapper import XArmAPI  # type: ignore

            self._arm = XArmAPI(self._ip, is_radian=False)
            self._arm.connect()
            self._arm.motion_enable(enable=True)
            self._arm.set_mode(0)
            self._arm.set_state(0)
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            if self._arm is not None:
                try:
                    self._arm.disconnect()
                except Exception:
                    pass
                self._arm = None
            self._connected = False

    # ------------------------------------------------------------------
    # Telemetry

    def status(self) -> ArmStatus:
        with self._lock:
            if self._mock:
                # Cheap sine on joint 1 so /status returns something live-looking.
                t = time.monotonic() - self._mock_t0
                joints = [15.0 * math.sin(t * 0.5), 0.0, 0.0, 0.0, 0.0, 0.0]
                return ArmStatus(
                    connected=True,
                    mock=True,
                    robot_mode=0,
                    state=0,
                    error_code=0,
                    warn_code=0,
                    gripper=self._gripper_state,
                    joints_deg=joints,
                    pose={"x": 200.0, "y": 0.0, "z": 250.0, "roll": 180.0, "pitch": 0.0, "yaw": 0.0},
                )
            if not self._connected or self._arm is None:
                return ArmStatus(
                    connected=False, mock=False, robot_mode=-1, state=-1,
                    error_code=-1, warn_code=-1, gripper=GRIPPER_UNKNOWN,
                )
            code, angles = self._arm.get_servo_angle(is_radian=False)
            _, pose = self._arm.get_position()
            err_code, warn_code = self._arm.get_err_warn_code()[1]
            return ArmStatus(
                connected=True,
                mock=False,
                robot_mode=self._arm.mode,
                state=self._arm.state,
                error_code=err_code,
                warn_code=warn_code,
                gripper=self._gripper_state,
                joints_deg=list(angles[:6]) if code == 0 else [0.0] * 6,
                pose={
                    "x": pose[0], "y": pose[1], "z": pose[2],
                    "roll": pose[3], "pitch": pose[4], "yaw": pose[5],
                },
            )

    # ------------------------------------------------------------------
    # Motion primitives — every call is short, blocking, lock-held.

    def go_home(self, speed_deg_s: float = 30.0) -> None:
        """Joint-space move to all-zero pose."""
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.set_servo_angle(
                angle=HOME_JOINTS_DEG, speed=speed_deg_s, wait=True, is_radian=False
            )

    def move_line(
        self,
        x: float, y: float, z: float,
        roll: float = 180.0, pitch: float = 0.0, yaw: float = 0.0,
        speed: float = 100.0, acc: float = 1000.0,
    ) -> None:
        """Cartesian linear (straight-line in task space) move.

        Use this for any motion where the TCP path matters (pick-and-place
        descents, retracts above obstacles, etc.). For point-to-point joint
        moves where path doesn't matter, prefer ``set_servo_angle``.
        """
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.set_position(
                x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw,
                speed=speed, mvacc=acc,
                motion_type=0, relative=False, wait=True,
            )

    def set_servo_angle(self, angles_deg: list[float], speed_deg_s: float = 30.0) -> None:
        """Joint-space move with point-to-point interpolation."""
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.set_servo_angle(
                angle=angles_deg, speed=speed_deg_s, wait=True, is_radian=False
            )

    # Backwards-compatible alias.
    def set_position(self, *args, **kwargs) -> None:
        return self.move_line(*args, **kwargs)

    def emergency_stop(self) -> None:
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.emergency_stop()
            self._arm.motion_enable(enable=True)
            self._arm.set_state(0)

    # ------------------------------------------------------------------
    # Lite 6 gripper. The Lite 6 has its own pneumatic gripper API in the
    # SDK, distinct from the standard xArm parallel-jaw gripper functions.

    def open_gripper(self) -> None:
        with self._lock:
            self._gripper_state = GRIPPER_OPEN
            if self._mock or self._arm is None:
                return
            self._arm.open_lite6_gripper()

    def close_gripper(self) -> None:
        with self._lock:
            self._gripper_state = GRIPPER_CLOSED
            if self._mock or self._arm is None:
                return
            self._arm.close_lite6_gripper()

    def stop_gripper(self) -> None:
        with self._lock:
            self._gripper_state = GRIPPER_STOPPED
            if self._mock or self._arm is None:
                return
            self._arm.stop_lite6_gripper()

    # ------------------------------------------------------------------
    # Error / warning handling.

    def get_errors(self) -> dict[str, int]:
        with self._lock:
            if self._mock or self._arm is None:
                return {"error_code": 0, "warn_code": 0}
            err, warn = self._arm.get_err_warn_code()[1]
            return {"error_code": err, "warn_code": warn}

    def clear_faults(self) -> None:
        """Clear error/warn codes and re-enable motion.

        After a collision, joint-limit, or other fault the arm latches an
        error code and refuses motion commands until the fault is cleared.
        Without this primitive the only recovery is a power cycle.
        """
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.clean_error()
            self._arm.clean_warn()
            self._arm.motion_enable(enable=True)
            self._arm.set_mode(0)
            self._arm.set_state(0)

    # ------------------------------------------------------------------
    # Configuration.

    def set_tcp_offset(
        self,
        x: float = 0.0, y: float = 0.0, z: float = 0.0,
        roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0,
    ) -> None:
        """Set tool center point offset (mm + degrees) from the flange."""
        with self._lock:
            if self._mock or self._arm is None:
                return
            self._arm.set_tcp_offset([x, y, z, roll, pitch, yaw])
            self._arm.set_state(0)

    # ------------------------------------------------------------------
    # Properties exposed for FastAPI / node use.

    @property
    def is_mock(self) -> bool:
        return self._mock

    @property
    def ip(self) -> str:
        return self._ip
