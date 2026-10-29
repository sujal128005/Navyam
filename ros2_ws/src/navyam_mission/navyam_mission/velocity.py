"""Velocity maths for the Nav2 -> ArduPilot bridge. Pure Python (no ROS imports)."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class VelocityLimits:
    max_xy: float = 0.6       # m/s, horizontal speed cap indoors
    max_yaw_rate: float = 0.8  # rad/s
    max_vz: float = 0.3       # m/s
    kz: float = 0.8           # 1/s, altitude P gain


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def body_command(vx: float, vy: float, yaw_rate: float, z: float | None, z_target: float,
                 lim: VelocityLimits) -> tuple[float, float, float, float]:
    """Nav2 body-frame (x forward, y left) command -> capped (vx, vy, vz, yaw_rate) with altitude hold.

    Nav2 plans in 2D, so vertical speed comes from a P controller on the EKF altitude.
    With no altitude estimate we command vz = 0 and let ArduPilot hold.
    """
    speed = math.hypot(vx, vy)
    if speed > lim.max_xy:
        scale = lim.max_xy / speed
        vx, vy = vx * scale, vy * scale
    vz = 0.0 if z is None else clamp(lim.kz * (z_target - z), -lim.max_vz, lim.max_vz)
    return vx, vy, vz, clamp(yaw_rate, -lim.max_yaw_rate, lim.max_yaw_rate)


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def earth_to_body(vx_e: float, vy_e: float, yaw: float) -> tuple[float, float]:
    """Rotate an ENU earth-frame horizontal velocity into the body frame (x forward, y left)."""
    c, s = math.cos(yaw), math.sin(yaw)
    return c * vx_e + s * vy_e, -s * vx_e + c * vy_e
