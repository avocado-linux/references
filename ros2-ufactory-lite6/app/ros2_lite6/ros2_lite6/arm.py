"""Thin wrapper around the xArm Python SDK with a thread-safe surface and a
mock fallback.

The reference runs in two modes:
  * Live  — LITE6_IP set to a reachable Lite 6 control box.
  * Mock  — LITE6_IP=mock, no SDK call, synthetic joint state. Lets people
            evaluate the rest of the stack without hardware.

Source for the SDK methods called below:
  https://github.com/xArm-Developer/xArm-Python-SDK

Threading model:
  * _sdk_lock  — short-held lock that serialises individual SDK calls (reads
                 and non-blocking writes). Never held for longer than one
                 network round-trip.
  * _cmd_lock  — serialises motion commands against each other so two HTTP
                 requests can't issue conflicting moves. Motion methods issue
                 a non-blocking SDK call under _sdk_lock, release it, then
                 poll for completion — so telemetry reads can interleave
                 freely while the arm is moving.
  * _telemetry_thread — a daemon thread that polls joint angles + pose at
                        ~60 Hz and writes a cached ArmStatus snapshot.
                        status() returns the cache instantly, never touching
                        the SDK, so the 30 Hz ROS publish timer is never
                        blocked by network I/O.
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

# How often the background telemetry thread polls the SDK (Hz).
_TELEMETRY_HZ = 60.0

# How often to poll for motion completion inside _wait_for_idle (seconds).
_MOTION_POLL_INTERVAL = 0.05

# How long _wait_for_idle waits for a just-issued (wait=False) move to register
# as "in motion" before concluding it was a no-op / already finished (seconds).
_MOTION_START_TIMEOUT = 0.5

# Upper bound on how long a single motion command may take before _wait_for_idle
# gives up (seconds). Prevents a faulted/stuck arm from spinning forever while
# holding _cmd_lock.
_MOTION_TIMEOUT = 30.0


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
    """Thread-safe facade over xArm SDK.

    Telemetry (status()) is lock-free — it reads a cached snapshot written by a
    background poller.  Motion commands serialise against each other via
    _cmd_lock but never block the telemetry path.
    """

    def __init__(self) -> None:
        self._sdk_lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._ip = os.environ.get("LITE6_IP", "192.168.1.117")
        self._mock = self._ip.lower() == "mock"
        self._arm = None  # XArmAPI instance once connected
        self._mock_t0 = time.monotonic()
        self._connected = False
        self._gripper_state = GRIPPER_UNKNOWN

        # Cached telemetry snapshot — written by _telemetry_loop, read by
        # status().  The reference is replaced atomically (Python GIL) so
        # readers never see a half-written object.
        self._cached_status: ArmStatus = ArmStatus(
            connected=False, mock=self._mock, robot_mode=-1, state=-1,
            error_code=-1, warn_code=-1, gripper=GRIPPER_UNKNOWN,
        )
        self._telemetry_stop = threading.Event()
        self._telemetry_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle

    def connect(self) -> None:
        with self._sdk_lock:
            if self._connected:
                return
            if self._mock:
                self._connected = True
            else:
                # Lazy import so mock mode doesn't drag in the SDK.
                from xarm.wrapper import XArmAPI  # type: ignore

                self._arm = XArmAPI(self._ip, is_radian=False)
                self._arm.connect()
                self._arm.motion_enable(enable=True)
                self._arm.set_mode(0)
                self._arm.set_state(0)
                self._connected = True
        # Start the poller once, outside the lock, for both mock and live.
        self._start_telemetry()

    def disconnect(self) -> None:
        self._telemetry_stop.set()
        with self._sdk_lock:
            if self._arm is not None:
                try:
                    self._arm.disconnect()
                except Exception:
                    pass
                self._arm = None
            self._connected = False
            # Refresh the cache so status() reflects the disconnect instead of
            # returning the last "connected" snapshot forever — the poller has
            # stopped and will no longer update it.
            self._cached_status = ArmStatus(
                connected=False, mock=self._mock, robot_mode=-1, state=-1,
                error_code=-1, warn_code=-1, gripper=self._gripper_state,
            )

    # ------------------------------------------------------------------
    # Background telemetry poller

    def _start_telemetry(self) -> None:
        # Stop and reap any previous poller before starting a new one. Without
        # this, a connect→disconnect→connect sequence would clear the stop event
        # (below) while an old thread is still sleeping in wait(), resurrecting
        # it — leaving two threads writing _cached_status with no way to stop
        # either independently.
        prev = self._telemetry_thread
        if prev is not None and prev.is_alive():
            self._telemetry_stop.set()
            prev.join(timeout=2.0)
        self._telemetry_stop.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop, name="arm-telemetry", daemon=True
        )
        self._telemetry_thread.start()

    def _telemetry_loop(self) -> None:
        """Poll the SDK at ~60 Hz and cache the result.

        Each iteration acquires _sdk_lock for just the duration of the SDK
        calls (~1-3 ms over Ethernet), so motion commands can still interleave.
        """
        interval = 1.0 / _TELEMETRY_HZ
        while not self._telemetry_stop.is_set():
            try:
                self._cached_status = self._read_status_from_sdk()
            except Exception:
                pass  # keep polling — transient SDK errors shouldn't kill the thread
            self._telemetry_stop.wait(interval)

    def _read_status_from_sdk(self) -> ArmStatus:
        """One synchronous SDK read, short-locked."""
        if self._mock:
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

        with self._sdk_lock:
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
    # Telemetry (public)

    def status(self) -> ArmStatus:
        """Return the latest cached telemetry snapshot.

        Lock-free — the 30 Hz ROS timer can call this without ever blocking on
        SDK I/O or waiting for a motion command to finish.
        """
        return self._cached_status

    # ------------------------------------------------------------------
    # Motion helpers

    def _wait_for_idle(self) -> None:
        """Block until the current motion finishes, faults, or times out.

        xArm state codes: 1 = in motion, 2 = ready/idle, 3 = paused,
        4 = stopped, 6 = decelerating. A wait=False move takes a moment to
        register, so we first wait (briefly) for the arm to *enter* state 1,
        then poll until it *leaves* it — reaching idle, or being stopped by a
        fault / e-stop. If motion never registers within _MOTION_START_TIMEOUT
        the move was a no-op (or already finished) and we return. The overall
        _MOTION_TIMEOUT bound guarantees we never spin here forever holding
        _cmd_lock when the arm is stuck or faulted.

        Called *outside* _sdk_lock so the telemetry poller keeps reading while
        we wait.
        """
        now = time.monotonic()
        deadline = now + _MOTION_TIMEOUT
        start_deadline = now + _MOTION_START_TIMEOUT
        started = False
        while time.monotonic() < deadline:
            with self._sdk_lock:
                if not self._connected or self._arm is None:
                    return
                state = self._arm.state
            if state == 1:  # in motion
                started = True
            elif started:  # was moving, now idle/stopped -> done
                return
            elif time.monotonic() >= start_deadline:
                return  # motion never registered (short / no-op move)
            time.sleep(_MOTION_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Motion primitives — _cmd_lock serialises moves; _sdk_lock is held only
    # for the brief SDK call itself, then released while we wait.

    def go_home(self, speed_deg_s: float = 30.0) -> None:
        """Joint-space move to all-zero pose."""
        with self._cmd_lock:
            with self._sdk_lock:
                if self._mock or self._arm is None:
                    return
                self._arm.set_servo_angle(
                    angle=HOME_JOINTS_DEG, speed=speed_deg_s, wait=False, is_radian=False
                )
            self._wait_for_idle()

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
        with self._cmd_lock:
            with self._sdk_lock:
                if self._mock or self._arm is None:
                    return
                self._arm.set_position(
                    x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw,
                    speed=speed, mvacc=acc,
                    motion_type=0, relative=False, wait=False,
                )
            self._wait_for_idle()

    def set_servo_angle(self, angles_deg: list[float], speed_deg_s: float = 30.0) -> None:
        """Joint-space move with point-to-point interpolation."""
        with self._cmd_lock:
            with self._sdk_lock:
                if self._mock or self._arm is None:
                    return
                self._arm.set_servo_angle(
                    angle=angles_deg, speed=speed_deg_s, wait=False, is_radian=False
                )
            self._wait_for_idle()

    # Backwards-compatible alias.
    def set_position(self, *args, **kwargs) -> None:
        return self.move_line(*args, **kwargs)

    def emergency_stop(self) -> None:
        with self._sdk_lock:
            if self._mock or self._arm is None:
                return
            self._arm.emergency_stop()
            self._arm.motion_enable(enable=True)
            self._arm.set_state(0)

    # ------------------------------------------------------------------
    # Lite 6 gripper. The Lite 6 has its own pneumatic gripper API in the
    # SDK, distinct from the standard xArm parallel-jaw gripper functions.

    def open_gripper(self) -> None:
        with self._sdk_lock:
            self._gripper_state = GRIPPER_OPEN
            if self._mock or self._arm is None:
                return
            self._arm.open_lite6_gripper()

    def close_gripper(self) -> None:
        with self._sdk_lock:
            self._gripper_state = GRIPPER_CLOSED
            if self._mock or self._arm is None:
                return
            self._arm.close_lite6_gripper()

    def stop_gripper(self) -> None:
        with self._sdk_lock:
            self._gripper_state = GRIPPER_STOPPED
            if self._mock or self._arm is None:
                return
            self._arm.stop_lite6_gripper()

    # ------------------------------------------------------------------
    # Error / warning handling.

    def get_errors(self) -> dict[str, int]:
        with self._sdk_lock:
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
        with self._sdk_lock:
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
        with self._sdk_lock:
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
