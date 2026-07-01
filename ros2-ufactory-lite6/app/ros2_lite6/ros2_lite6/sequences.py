"""Canned motion sequences. Extend this file to add new behaviors and
push them to the device via ``avocado deploy``.

All joint angles are in degrees. The Lite 6 joint layout:
  joint1: base rotation       (-360 to +360)
  joint2: shoulder             (-150 to +150)
  joint3: elbow                (  0  to +225)  ** no negative! **
  joint4: wrist rotation       (-360 to +360)
  joint5: wrist bend           (-150 to +150)
  joint6: flange rotation      (-360 to +360)

Home pose (all zeros) is the arm folded compact, TCP at ~[85, 0, 152] mm.
Negative J2 lifts the shoulder up; positive J3 bends the elbow forward/out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .arm import ArmController, HOME_JOINTS_DEG


def home(arm: ArmController) -> None:
    """Return to the all-zero joint pose."""
    arm.go_home()


def wave(arm: ArmController, oscillations: int = 3) -> None:
    """Wave by raising the arm high, then rotating the wrist side to side."""
    # Raise arm: shoulder up, elbow out, wrist angled
    raised = [0.0, -45.0, 45.0, 0.0, 45.0, 0.0]
    arm.set_servo_angle(raised, speed_deg_s=40.0)
    time.sleep(0.3)

    # Wave by rotating the flange (joint 6) back and forth
    for _ in range(oscillations):
        wave_left = [0.0, -45.0, 45.0, 0.0, 45.0, -50.0]
        wave_right = [0.0, -45.0, 45.0, 0.0, 45.0, 50.0]
        arm.set_servo_angle(wave_left, speed_deg_s=90.0)
        arm.set_servo_angle(wave_right, speed_deg_s=90.0)

    # Return to center, then home
    arm.set_servo_angle(raised, speed_deg_s=60.0)
    time.sleep(0.2)
    arm.go_home()


def present(arm: ArmController) -> None:
    """Extend the arm forward and present the gripper — a "ta-da" pose.

    Useful for showing off the arm's reach or presenting an object
    held in the gripper.
    """
    # Lift up first
    arm.set_servo_angle([0.0, -30.0, 30.0, 0.0, 45.0, 0.0], speed_deg_s=40.0)
    time.sleep(0.2)

    # Extend forward — full reach presentation
    arm.move_line(x=300.0, y=0.0, z=300.0, roll=180.0, pitch=0.0, yaw=0.0, speed=150.0)
    time.sleep(0.5)

    # Open gripper for flourish
    arm.open_gripper()
    time.sleep(1.0)

    # Close gripper
    arm.close_gripper()
    time.sleep(0.5)

    arm.go_home()


def scan(arm: ArmController, sweep_deg: float = 120.0, speed: float = 25.0) -> None:
    """Sweep the arm in an arc as if scanning a workspace.

    Extends the arm forward, then rotates the base left-to-right
    and back. Useful for demos with a camera mounted on the flange.
    """
    half = sweep_deg / 2.0

    # Extend arm forward at a working height, angled slightly down
    survey_pose = [0.0, 20.0, 50.0, 0.0, 30.0, 0.0]
    arm.set_servo_angle(survey_pose, speed_deg_s=40.0)
    time.sleep(0.3)

    # Sweep left
    left = list(survey_pose)
    left[0] = -half
    arm.set_servo_angle(left, speed_deg_s=speed)

    # Sweep right
    right = list(survey_pose)
    right[0] = half
    arm.set_servo_angle(right, speed_deg_s=speed)

    # Return to center
    arm.set_servo_angle(survey_pose, speed_deg_s=speed)
    time.sleep(0.3)

    arm.go_home()


def nod(arm: ArmController, nods: int = 3) -> None:
    """Nod the wrist up and down — a "yes" gesture.

    Raises the arm first so the motion is visible, then bobs
    the wrist (joint 5) up and down.
    """
    # Raise arm up and out
    raised = [0.0, -20.0, 40.0, 0.0, 40.0, 0.0]
    arm.set_servo_angle(raised, speed_deg_s=40.0)
    time.sleep(0.3)

    for _ in range(nods):
        nod_down = [0.0, -20.0, 40.0, 0.0, 70.0, 0.0]
        nod_up = [0.0, -20.0, 40.0, 0.0, 20.0, 0.0]
        arm.set_servo_angle(nod_down, speed_deg_s=80.0)
        arm.set_servo_angle(nod_up, speed_deg_s=80.0)

    arm.set_servo_angle(raised, speed_deg_s=50.0)
    time.sleep(0.2)
    arm.go_home()


def dance(arm: ArmController) -> None:
    """A short choreographed sequence that exercises multiple joints.

    Cycles through a few poses that look fluid and demonstrate the
    arm's range of motion — good for trade show demos.
    """
    speed = 50.0

    # Pose 1: reach high right
    arm.set_servo_angle([45.0, -45.0, 45.0, 0.0, 30.0, 0.0], speed_deg_s=speed)
    time.sleep(0.1)

    # Pose 2: sweep low left
    arm.set_servo_angle([-45.0, 30.0, 70.0, 90.0, 60.0, 0.0], speed_deg_s=speed)
    time.sleep(0.1)

    # Pose 3: reach high left
    arm.set_servo_angle([-45.0, -45.0, 45.0, 0.0, 30.0, 0.0], speed_deg_s=speed)
    time.sleep(0.1)

    # Pose 4: sweep low right
    arm.set_servo_angle([45.0, 30.0, 70.0, -90.0, 60.0, 0.0], speed_deg_s=speed)
    time.sleep(0.1)

    # Pose 5: extend forward, wrist twist
    arm.set_servo_angle([0.0, 10.0, 60.0, 0.0, 45.0, 90.0], speed_deg_s=speed)
    time.sleep(0.1)
    arm.set_servo_angle([0.0, 10.0, 60.0, 0.0, 45.0, -90.0], speed_deg_s=speed)
    time.sleep(0.1)

    arm.go_home(speed_deg_s=40.0)


def square(arm: ArmController, edge_mm: float = 100.0, speed: float = 100.0) -> None:
    """Trace a horizontal square in Cartesian space.

    Useful as a smoke test for the Cartesian linear move path.
    """
    cx, cy, cz = 250.0, 0.0, 250.0
    half = edge_mm / 2.0
    corners = [
        (cx + half, cy + half),
        (cx + half, cy - half),
        (cx - half, cy - half),
        (cx - half, cy + half),
        (cx + half, cy + half),
    ]
    for x, y in corners:
        arm.move_line(x=x, y=y, z=cz, speed=speed)
        time.sleep(0.05)
    arm.go_home()


@dataclass
class PickPlacePose:
    """Cartesian pose for a pick or place point.

    Z is the *grasp* height — the planner adds a vertical clearance for
    approach/retreat so we don't drag through obstacles.
    """
    x: float
    y: float
    z: float
    roll: float = 180.0
    pitch: float = 0.0
    yaw: float = 0.0


def pick_and_place(
    arm: ArmController,
    source: PickPlacePose,
    dest: PickPlacePose,
    *,
    hover_clearance_mm: float = 80.0,
    travel_speed: float = 200.0,
    approach_speed: float = 60.0,
    grip_settle_s: float = 0.4,
) -> None:
    """Grip an object at ``source`` and release it at ``dest``.

    Standard top-down pick-and-place: approach from above, descend, close
    gripper, ascend, translate to destination, descend, open gripper,
    ascend, return home.

    All coordinates are in robot base frame (mm + degrees). Roll defaults
    to 180deg (TCP pointing down) for a top-down grasp.
    """
    src_hover = PickPlacePose(
        x=source.x, y=source.y, z=source.z + hover_clearance_mm,
        roll=source.roll, pitch=source.pitch, yaw=source.yaw,
    )
    dst_hover = PickPlacePose(
        x=dest.x, y=dest.y, z=dest.z + hover_clearance_mm,
        roll=dest.roll, pitch=dest.pitch, yaw=dest.yaw,
    )

    # Open gripper before we go anywhere — defensive.
    arm.open_gripper()
    time.sleep(grip_settle_s)

    # Approach source.
    arm.move_line(
        x=src_hover.x, y=src_hover.y, z=src_hover.z,
        roll=src_hover.roll, pitch=src_hover.pitch, yaw=src_hover.yaw,
        speed=travel_speed,
    )
    arm.move_line(
        x=source.x, y=source.y, z=source.z,
        roll=source.roll, pitch=source.pitch, yaw=source.yaw,
        speed=approach_speed,
    )

    # Grip.
    arm.close_gripper()
    time.sleep(grip_settle_s)

    # Retreat -> travel -> approach destination.
    arm.move_line(
        x=src_hover.x, y=src_hover.y, z=src_hover.z,
        roll=src_hover.roll, pitch=src_hover.pitch, yaw=src_hover.yaw,
        speed=approach_speed,
    )
    arm.move_line(
        x=dst_hover.x, y=dst_hover.y, z=dst_hover.z,
        roll=dst_hover.roll, pitch=dst_hover.pitch, yaw=dst_hover.yaw,
        speed=travel_speed,
    )
    arm.move_line(
        x=dest.x, y=dest.y, z=dest.z,
        roll=dest.roll, pitch=dest.pitch, yaw=dest.yaw,
        speed=approach_speed,
    )

    # Release.
    arm.open_gripper()
    time.sleep(grip_settle_s)

    # Retreat -> home.
    arm.move_line(
        x=dst_hover.x, y=dst_hover.y, z=dst_hover.z,
        roll=dst_hover.roll, pitch=dst_hover.pitch, yaw=dst_hover.yaw,
        speed=approach_speed,
    )
    arm.go_home()
