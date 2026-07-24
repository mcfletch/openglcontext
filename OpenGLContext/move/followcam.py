"""A fixed-offset follow camera for third-person / overhead demos.

The camera sits at a constant offset from a target and looks at it — no user
control, no orbiting.  Each frame the caller sets the target (usually a moving
object's position) and calls :meth:`apply`, which writes the position and
orientation onto a :class:`~OpenGLContext.move.viewplatform.ViewPlatform`.

It also supports **holding**: freeze on the current target and ignore new ones
until released.  The marble demo uses this to keep the view locked on the square a
marble fell from while the respawn penalty elapses, instead of chasing the marble
into the void.

Orientation convention: this targets the **core-profile** view path, where
``ViewPlatform`` builds the modelview from ``modelMatrix`` /
``quaternion.matrix``.  :func:`look_at_orientation` returns the VRML axis-angle
that (after ``setOrientation`` negates it, as it does for every VRML orientation)
places the target on the camera's view -Z axis — verified end-to-end against
``ViewPlatform.modelMatrix`` in ``tests/test_followcam.py``.
"""
from typing import Any, Optional, Tuple

import numpy as np


def _normalize(v: Any) -> np.ndarray:
    v = np.asarray(v, dtype='d')
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def look_at_orientation(eye: Any, target: Any,
                        up: Any = (0.0, 1.0, 0.0)) -> Tuple[float, float, float, float]:
    """VRML axis-angle ``(x, y, z, radians)`` orienting a camera at ``eye`` to
    look at ``target``.

    Builds the camera basis (right, up, backward) in world space and converts the
    resulting rotation matrix to an axis-angle.  ``up`` is the desired world up;
    pass a different up (e.g. ``(0,0,-1)``) when looking straight down, where the
    default up is degenerate.
    """
    eye = np.asarray(eye, dtype='d')
    target = np.asarray(target, dtype='d')

    backward = _normalize(eye - target)             # camera local +Z
    right = _normalize(np.cross(_normalize(up), backward))  # camera local +X
    true_up = np.cross(backward, right)             # camera local +Y
    # Columns are where the camera's local x/y/z land in world space (the
    # camera-local → world rotation).  ViewPlatform.setOrientation negates the
    # angle and the core modelMatrix consumes it so this basis becomes the view.
    R = np.column_stack([right, true_up, backward])
    return _matrix_to_axis_angle(R)


def _matrix_to_axis_angle(R: np.ndarray) -> Tuple[float, float, float, float]:
    """Convert a 3×3 rotation matrix to VRML axis-angle ``(x, y, z, radians)``."""
    trace = np.trace(R)
    cos_angle = np.clip((trace - 1.0) / 2.0, -1.0, 1.0)
    angle = np.arccos(cos_angle)
    if angle < 1e-9:
        return (0.0, 1.0, 0.0, 0.0)
    if angle > np.pi - 1e-6:
        # Near 180°: axis from the largest diagonal term, sign-recovered off-diagonal.
        d = np.array([R[0, 0], R[1, 1], R[2, 2]])
        k = int(np.argmax(d))
        axis = np.zeros(3)
        axis[k] = np.sqrt(max((R[k, k] + 1.0) / 2.0, 0.0))
        other = [(k + 1) % 3, (k + 2) % 3]
        for j in other:
            axis[j] = R[k, j] / (2.0 * axis[k]) if axis[k] > 1e-9 else 0.0
        axis = _normalize(axis)
        return (float(axis[0]), float(axis[1]), float(axis[2]), float(angle))
    axis = np.array([R[2, 1] - R[1, 2],
                     R[0, 2] - R[2, 0],
                     R[1, 0] - R[0, 1]])
    axis = _normalize(axis)
    return (float(axis[0]), float(axis[1]), float(axis[2]), float(angle))


class FollowCamera:
    """Drive a ``ViewPlatform`` to a fixed offset from a target, looking at it."""

    def __init__(self, platform: Any, offset: Any = (0.0, 14.0, 14.0),
                 up: Any = (0.0, 1.0, 0.0)) -> None:
        self.platform = platform
        self.offset = np.asarray(offset, dtype='d')
        self.up = np.asarray(up, dtype='d')
        self._target = np.zeros(3)
        self._held_target: Optional[np.ndarray] = None

    def target(self, position: Any) -> None:
        """Record the live point to follow.

        Always updates the live target; while holding, :meth:`apply` simply
        ignores it, so on :meth:`release` the camera snaps to the most recent
        live target rather than a stale one.
        """
        self._target = np.asarray(position, dtype='d')[:3]

    def hold(self) -> None:
        """Freeze the camera on the current target until :meth:`release`."""
        if self._held_target is None:
            self._held_target = self._target.copy()

    def release(self) -> None:
        """Resume following live targets."""
        self._held_target = None

    @property
    def is_holding(self) -> bool:
        return self._held_target is not None

    @property
    def active_target(self) -> np.ndarray:
        return self._held_target if self._held_target is not None else self._target

    def apply(self) -> None:
        """Write the camera pose onto the platform for this frame."""
        target = self.active_target
        eye = target + self.offset
        self.platform.setPosition(tuple(eye))
        self.platform.setOrientation(look_at_orientation(eye, target, self.up))
