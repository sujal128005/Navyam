"""Image-to-3D helpers for the survivor detector. Needs numpy, no ROS."""
from __future__ import annotations

import numpy as np


def pixel_to_point(u: float, v: float, depth_m: float, fx: float, fy: float, cx: float, cy: float) -> tuple[float, float, float]:
    """Pinhole back-projection into the camera *optical* frame (x right, y down, z forward)."""
    return (u - cx) * depth_m / fx, (v - cy) * depth_m / fy, depth_m


def box_depth_m(depth: np.ndarray, box: tuple[float, float, float, float], depth_scale: float,
                shrink: float = 0.5, min_m: float = 0.2, max_m: float = 8.0, min_pixels: int = 10) -> float | None:
    """Median depth (metres) of the central part of a detection box, ignoring holes and outliers.

    ``shrink`` keeps that fraction of the box width/height around its centre, so the floor or wall
    around a person does not pull the estimate. Returns None if too few valid pixels remain.
    """
    x1, y1, x2, y2 = box
    h, w = depth.shape[:2]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half_w, half_h = (x2 - x1) * shrink / 2, (y2 - y1) * shrink / 2
    xa, xb = max(int(cx - half_w), 0), min(int(np.ceil(cx + half_w)), w)
    ya, yb = max(int(cy - half_h), 0), min(int(np.ceil(cy + half_h)), h)
    if xb <= xa or yb <= ya:
        return None
    patch = depth[ya:yb, xa:xb].astype(np.float64) * depth_scale
    valid = patch[np.isfinite(patch) & (patch > min_m) & (patch < max_m)]
    if valid.size < min_pixels:
        return None
    return float(np.median(valid))
