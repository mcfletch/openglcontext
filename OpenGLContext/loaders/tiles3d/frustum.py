"""View-frustum culling for tileset traversal.

A frustum built from a view-projection matrix classifies tile bounding spheres as
visible or not, so the traversal only refines and streams tiles the camera can see.
This bounds the resident working set to a window around the view rather than the whole
world.

Matrices are row-vector-on-the-right convention: clip = M @ [x, y, z, 1]. Plane
extraction is the Gribb-Hartmann method.
"""
from typing import Any

import numpy as np


def perspective(fovy: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / np.tan(fovy / 2.0)
    m = np.zeros((4, 4), dtype="d")
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: Any, center: Any, up: Any) -> np.ndarray:
    eye = np.asarray(eye, dtype="d")
    center = np.asarray(center, dtype="d")
    up = np.asarray(up, dtype="d")
    f = center - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4, dtype="d")
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -s.dot(eye)
    m[1, 3] = -u.dot(eye)
    m[2, 3] = f.dot(eye)
    return m


def view_projection(eye: Any, center: Any, up: Any, fovy: float, aspect: float,
                    near: float, far: float) -> np.ndarray:
    return perspective(fovy, aspect, near, far) @ look_at(eye, center, up)


class Frustum:
    """Six inward-facing planes; `contains_sphere` for cheap culling."""

    def __init__(self, planes: np.ndarray) -> None:
        self.planes = planes            # (6, 4): a,b,c,d, inside where a·x+d >= 0

    @classmethod
    def from_matrix(cls, m: np.ndarray) -> "Frustum":
        rows = [m[3] + m[0], m[3] - m[0],   # left, right
                m[3] + m[1], m[3] - m[1],   # bottom, top
                m[3] + m[2], m[3] - m[2]]   # near, far
        planes = np.array(rows, dtype="d")
        norms = np.linalg.norm(planes[:, :3], axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return cls(planes / norms)

    def contains_sphere(self, center: Any, radius: float) -> bool:
        center = np.asarray(center, dtype="d")
        d = self.planes[:, :3] @ center + self.planes[:, 3]
        return bool(np.all(d >= -radius))
