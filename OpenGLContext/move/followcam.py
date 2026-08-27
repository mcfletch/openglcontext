"""A fixed-offset follow camera for third-person / overhead demos.

The camera sits at a constant offset from a target and looks at it — no user
control, no orbiting.  Each frame the caller sets the target (usually a moving
object's position) and calls :meth:`apply`, which writes the position and
orientation onto a :class:`~OpenGLContext.move.viewplatform.ViewPlatform`.

It also supports **holding**: freeze on the current target and ignore new ones
until released.  The marble demo uses this to keep the view locked on the square a
marble fell from while the respawn penalty elapses, instead of chasing the marble
into the void.

And it supports **pulling back**: a camera at one fixed distance shows the same
amount of world at every speed, which is least useful exactly when the target is
moving fastest and the player most needs to see what is coming.  Give it a
``pull_back`` fraction and feed :meth:`advance` the target's speed each frame, and
the offset eases outward with speed and back in again as the target slows.  The
default is zero, so a camera that does not ask for it behaves exactly as before.

Orientation convention: this targets the **core-profile** view path, where
``ViewPlatform`` builds the modelview from ``modelMatrix`` /
``quaternion.matrix``.  :func:`look_at_orientation` returns the VRML axis-angle
that (after ``setOrientation`` negates it, as it does for every VRML orientation)
places the target on the camera's view -Z axis — verified end-to-end against
``ViewPlatform.modelMatrix`` in ``tests/test_followcam.py``.
"""
import math
from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext import quaternion


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
    """A 3x3 rotation matrix as VRML axis-angle ``(x, y, z, radians)``.

    ``R``'s columns are where the rotated frame's axes land, which is the
    column-vector convention; :func:`quaternion.fromMatrix` reads the
    row-vector one the rest of the engine composes in, so it is handed the
    transpose.
    """
    return quaternion.fromMatrix(np.asarray(R, 'd').T).XYZR()


class FollowCamera:
    """Drive a ``ViewPlatform`` to a fixed offset from a target, looking at it."""

    def __init__(self, platform: Any, offset: Any = (0.0, 14.0, 14.0),
                 up: Any = (0.0, 1.0, 0.0), pull_back: float = 0.0,
                 pull_back_speed: float = 1.0, pull_back_rate: float = 3.0) -> None:
        """Follow ``platform``'s target from ``offset``, ``up`` fixing the roll.

        ``pull_back`` is the extra fraction of ``offset`` the camera reaches at
        ``pull_back_speed`` -- 0.5 means half again as far away -- ramping
        linearly from nothing at a standstill and holding at the limit above that
        speed.  ``pull_back_rate`` is how quickly the distance eases toward the
        one the current speed asks for, in nats per second: higher is snappier,
        and the easing is what keeps a speed spike from snapping the view.

        With the default ``pull_back`` of zero the distance never changes and
        :meth:`advance` need not be called at all.
        """
        self.platform = platform
        self.offset = np.asarray(offset, dtype='d')
        self.up = np.asarray(up, dtype='d')
        self.pull_back = float(pull_back)
        # A zero or negative full-speed would divide by nothing / invert the ramp.
        self.pull_back_speed = max(float(pull_back_speed), 1e-6)
        self.pull_back_rate = float(pull_back_rate)
        self._distance_scale = 1.0
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

    @property
    def distance_scale(self) -> float:
        """What the offset is currently multiplied by; 1.0 at a standstill."""
        return self._distance_scale

    def advance(self, dt: float, speed: float = 0.0) -> None:
        """Ease the follow distance toward the one ``speed`` asks for.

        Call once a frame with the elapsed time and the target's speed, before
        :meth:`apply`.  The easing is exponential in *elapsed time* rather than
        in frames, so the same run frames the same way on a fast machine and a
        slow one.
        """
        if self.pull_back == 0.0 or dt <= 0.0:
            return
        wanted = 1.0 + self.pull_back * min(speed / self.pull_back_speed, 1.0)
        approach = 1.0 - math.exp(-self.pull_back_rate * dt)
        self._distance_scale += (wanted - self._distance_scale) * approach

    def apply(self) -> None:
        """Write the camera pose onto the platform for this frame."""
        target = self.active_target
        eye = target + self.offset * self._distance_scale
        self.platform.setPosition(tuple(eye))
        self.platform.setOrientation(look_at_orientation(eye, target, self.up))
