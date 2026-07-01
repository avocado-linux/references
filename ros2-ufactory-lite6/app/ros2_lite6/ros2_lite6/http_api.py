"""FastAPI surface for non-ROS clients.

The HTTP API is the load-bearing UX choice: a customer without a ROS 2
laptop can control the arm with ``curl`` or the bundled web UI served at
``/``. ROS 2-equipped customers get the same arm via ``/joint_states``.
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .arm import ArmController
from . import sequences


# --------------------------------------------------------------------------
# Request models

class MoveLineRequest(BaseModel):
    """Cartesian linear move target. Coordinates in mm + degrees."""
    x: float
    y: float
    z: float
    roll: float = 180.0
    pitch: float = 0.0
    yaw: float = 0.0
    speed: float = Field(default=100.0, ge=1.0, le=400.0)


class MoveJointRequest(BaseModel):
    """Joint-space move target. Six joint angles in degrees."""
    angles_deg: list[float] = Field(min_length=6, max_length=6)
    speed_deg_s: float = Field(default=30.0, ge=1.0, le=120.0)


class PickPlaceRequest(BaseModel):
    """Pick-and-place between two top-down grasp poses."""
    source_x: float
    source_y: float
    source_z: float
    dest_x: float
    dest_y: float
    dest_z: float
    hover_clearance_mm: float = 80.0
    travel_speed: float = 200.0
    approach_speed: float = 60.0


class TcpOffsetRequest(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


# --------------------------------------------------------------------------

def _resolve_static_dir() -> str:
    """Find the static/ directory shipped with the package.

    Tries the ament_index lookup first (correct path inside the container),
    falls back to a sibling-of-this-file path for dev / mock runs.
    """
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory("ros2_lite6")
        candidate = os.path.join(share, "static")
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass
    return os.path.join(os.path.dirname(__file__), "static")


def _run_threaded(fn, *args, **kwargs) -> None:
    """Spawn fn(*args, **kwargs) on a daemon thread.

    Motion is blocking on the arm side; if we ran it inline the HTTP
    handler would block the uvicorn worker for the duration of the move.
    """
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def build_app(arm: ArmController) -> FastAPI:
    app = FastAPI(title="ROS 2 Lite 6 Controller")

    static_dir = _resolve_static_dir()

    # ----------------------------------------------------------------------
    # Telemetry

    @app.get("/status")
    def status() -> dict:
        s = arm.status()
        return {
            "connected": s.connected,
            "mock": s.mock,
            "ip": arm.ip,
            "robot_mode": s.robot_mode,
            "state": s.state,
            "error_code": s.error_code,
            "warn_code": s.warn_code,
            "gripper": s.gripper,
            "joints_deg": s.joints_deg,
            "pose": s.pose,
        }

    # ----------------------------------------------------------------------
    # Sequences

    @app.post("/home")
    def go_home() -> dict:
        _run_threaded(sequences.home, arm)
        return {"accepted": "home"}

    @app.post("/wave")
    def wave() -> dict:
        _run_threaded(sequences.wave, arm)
        return {"accepted": "wave"}

    @app.post("/present")
    def present() -> dict:
        _run_threaded(sequences.present, arm)
        return {"accepted": "present"}

    @app.post("/scan")
    def scan() -> dict:
        _run_threaded(sequences.scan, arm)
        return {"accepted": "scan"}

    @app.post("/nod")
    def nod() -> dict:
        _run_threaded(sequences.nod, arm)
        return {"accepted": "nod"}

    @app.post("/dance")
    def dance() -> dict:
        _run_threaded(sequences.dance, arm)
        return {"accepted": "dance"}

    @app.post("/square")
    def square() -> dict:
        _run_threaded(sequences.square, arm)
        return {"accepted": "square"}

    @app.post("/pick_and_place")
    def pick_and_place(req: PickPlaceRequest) -> dict:
        source = sequences.PickPlacePose(x=req.source_x, y=req.source_y, z=req.source_z)
        dest = sequences.PickPlacePose(x=req.dest_x, y=req.dest_y, z=req.dest_z)
        _run_threaded(
            sequences.pick_and_place, arm, source, dest,
            hover_clearance_mm=req.hover_clearance_mm,
            travel_speed=req.travel_speed,
            approach_speed=req.approach_speed,
        )
        return {"accepted": req.model_dump()}

    # ----------------------------------------------------------------------
    # Motion primitives

    @app.post("/move/line")
    def move_line(req: MoveLineRequest) -> dict:
        _run_threaded(
            arm.move_line,
            x=req.x, y=req.y, z=req.z,
            roll=req.roll, pitch=req.pitch, yaw=req.yaw,
            speed=req.speed,
        )
        return {"accepted": req.model_dump()}

    @app.post("/move/joint")
    def move_joint(req: MoveJointRequest) -> dict:
        _run_threaded(arm.set_servo_angle, req.angles_deg, req.speed_deg_s)
        return {"accepted": req.model_dump()}

    # Backwards-compatible alias for /move (existing curl examples).
    @app.post("/move")
    def move_compat(req: MoveLineRequest) -> dict:
        return move_line(req)

    # ----------------------------------------------------------------------
    # Gripper

    @app.post("/gripper/open")
    def gripper_open() -> dict:
        arm.open_gripper()
        return {"gripper": "open"}

    @app.post("/gripper/close")
    def gripper_close() -> dict:
        arm.close_gripper()
        return {"gripper": "closed"}

    @app.post("/gripper/stop")
    def gripper_stop() -> dict:
        arm.stop_gripper()
        return {"gripper": "stopped"}

    # ----------------------------------------------------------------------
    # Faults / config

    @app.post("/clear")
    def clear() -> dict:
        arm.clear_faults()
        return {"cleared": True, "errors": arm.get_errors()}

    @app.post("/tcp_offset")
    def tcp_offset(req: TcpOffsetRequest) -> dict:
        arm.set_tcp_offset(req.x, req.y, req.z, req.roll, req.pitch, req.yaw)
        return {"accepted": req.model_dump()}

    # ----------------------------------------------------------------------
    # Safety

    @app.post("/estop")
    def estop() -> dict:
        arm.emergency_stop()
        return {"accepted": "estop"}

    # ----------------------------------------------------------------------
    # UI — single-file HTML + vanilla JS, served at /

    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/")
        def index() -> FileResponse:
            index_path = os.path.join(static_dir, "index.html")
            if not os.path.isfile(index_path):
                raise HTTPException(status_code=404, detail="index.html missing")
            return FileResponse(index_path)

    return app
