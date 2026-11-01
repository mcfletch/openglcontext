"""Which way a character faces, how it lies on the ground, and how big it is.

A third-person character's node needs a yaw that follows where it goes, a tilt
that follows the ground under it, a lean into a turn, and a scale and offset
that put a model of any size inside its collision capsule with its feet on the
capsule's base. :class:`Facing` holds the first three and :func:`fit_to_height`
works out the last, with no GL and no scenegraph::

    facing = Facing(turn_rate=math.radians(540), lean=0.02)
    ...
    pose = facing.update(dt, velocity=character.velocity,
                         normal=ground_normal, acceleration=character.acceleration)
    node.rotation = pose.rotation

``heading`` is radians about +Y measured from +Z, so a heading ``h`` faces
``(sin h, 0, cos h)`` and is a ``Transform`` rotation of ``(0, 1, 0, h)``
(the convention of :mod:`~OpenGLContext.character.wander`). The pose is the
rotation ``yaw(heading) * pitch * roll``: the roll is about the body's own
forward axis, the pitch about its own sideways axis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from OpenGLContext import quaternion

__all__ = ['Facing', 'FacingPose', 'Fit', 'fit_to_height', 'model_bounds']

#: Metres a second of ground speed below which a character is not turned to
#: face its velocity.
MIN_TURN_SPEED = 0.1


@dataclass(frozen=True)
class FacingPose:
    """A character's orientation for one frame."""

    #: Radians about +Y from +Z, in (-pi, pi].
    heading: float
    #: Radians about the body's sideways axis; negative lifts the front.
    pitch: float
    #: Radians about the body's forward axis, ground and lean together.
    roll: float
    #: The same as a VRML axis-angle ``(x, y, z, radians)``.
    rotation: tuple[float, float, float, float]


def _wrap(angle: float) -> float:
    """``angle`` brought into ``(-pi, pi]``."""
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return math.pi if wrapped == -math.pi else wrapped


def _ease(rate: float, dt: float) -> float:
    """The share of the way to a target an exponential ease covers in ``dt``."""
    return 1.0 - math.exp(-rate * dt)


class Facing:
    """The heading, tilt and lean of one character.

    ``turn_rate`` is radians a second the heading turns at. ``align_to_ground``
    pitches and rolls the body to the ground normal, easing at ``ground_rate``
    (an exponential rate in 1/s) and never past ``max_tilt`` radians. ``lean``
    is radians of roll per metre a second squared of sideways acceleration, 0
    for none, limited to ``max_lean`` and eased at ``lean_rate``.
    """

    def __init__(self, *, turn_rate: float = math.radians(720.0),
                 align_to_ground: bool = True, ground_rate: float = 10.0,
                 max_tilt: float = math.radians(50.0), lean: float = 0.0,
                 max_lean: float = math.radians(25.0), lean_rate: float = 8.0,
                 heading: float = 0.0) -> None:
        self.turn_rate = float(turn_rate)
        self.align_to_ground = bool(align_to_ground)
        self.ground_rate = float(ground_rate)
        self.max_tilt = float(max_tilt)
        self.lean = float(lean)
        self.max_lean = float(max_lean)
        self.lean_rate = float(lean_rate)
        self.heading = _wrap(float(heading))
        self.pitch = 0.0
        self.roll = 0.0
        self._ground_roll = 0.0
        self._lean_roll = 0.0

    def reset(self, heading: float = 0.0) -> None:
        """Face ``heading`` upright, with no easing in progress."""
        self.heading = _wrap(float(heading))
        self.pitch = self.roll = self._ground_roll = self._lean_roll = 0.0

    def update(self, dt: float, *, velocity: Any = None, aim: Any = None,
               normal: Any = (0.0, 1.0, 0.0), acceleration: Any = None
               ) -> FacingPose:
        """Move the pose on by ``dt`` seconds.

        The heading turns toward ``aim``, a direction as ``(x, z)`` or
        ``(x, y, z)``, or failing that toward the horizontal part of
        ``velocity``; with neither it stays. ``normal`` is the ground's unit
        normal, and ``acceleration`` the character's acceleration in world
        space, of which the part across the heading is what leans the body.
        """
        target = self._wanted_heading(velocity, aim)
        if target is not None:
            step = self.turn_rate * dt
            difference = _wrap(target - self.heading)
            self.heading = _wrap(self.heading + max(-step, min(step, difference)))
        forward = np.array([math.sin(self.heading), 0.0, math.cos(self.heading)])
        across = np.array([math.cos(self.heading), 0.0, -math.sin(self.heading)])
        ground = _ease(self.ground_rate, dt)
        pitch_wanted, roll_wanted = (
            self._tilt(normal, forward, across) if self.align_to_ground else (0.0, 0.0))
        self.pitch += (pitch_wanted - self.pitch) * ground
        self._ground_roll += (roll_wanted - self._ground_roll) * ground
        sideways = 0.0 if acceleration is None else float(
            np.asarray(acceleration, 'd').reshape(-1)[:3] @ across)
        lean_wanted = max(-self.max_lean, min(self.max_lean, -self.lean * sideways))
        self._lean_roll += (lean_wanted - self._lean_roll) * _ease(self.lean_rate, dt)
        self.roll = self._ground_roll + self._lean_roll
        return FacingPose(self.heading, self.pitch, self.roll, self._rotation())

    @staticmethod
    def _wanted_heading(velocity: Any, aim: Any) -> Optional[float]:
        """The heading a direction names, from the aim or else the velocity."""
        if aim is not None:
            direction = np.asarray(aim, 'd').reshape(-1)
            direction = direction[[0, -1]] if len(direction) >= 3 else direction[:2]
            if float(np.hypot(*direction)) > 1e-9:
                return math.atan2(direction[0], direction[1])
        if velocity is not None:
            moving = np.asarray(velocity, 'd').reshape(-1)[[0, 2]]
            if float(np.hypot(*moving)) > MIN_TURN_SPEED:
                return math.atan2(moving[0], moving[1])
        return None

    def _tilt(self, normal: Any, forward: np.ndarray, across: np.ndarray
              ) -> tuple[float, float]:
        """The pitch and roll that lay the body's up on ``normal``."""
        up = np.asarray(normal, 'd').reshape(-1)[:3]
        length = float(np.linalg.norm(up))
        if length < 1e-9:
            return 0.0, 0.0
        up = up / length
        pitch = math.atan2(float(up @ forward), float(up[1]))
        roll = -math.asin(max(-1.0, min(1.0, float(up @ across))))
        limit = self.max_tilt
        return max(-limit, min(limit, pitch)), max(-limit, min(limit, roll))

    def _rotation(self) -> tuple[float, float, float, float]:
        """The heading, pitch and roll as an axis-angle."""
        cy, sy = math.cos(self.heading), math.sin(self.heading)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        yaw = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
        pitch = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
        roll = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]])
        # Columns are where the body's axes land; fromMatrix reads rows.
        x, y, z, angle = quaternion.fromMatrix((yaw @ pitch @ roll).T).XYZR()
        return float(x), float(y), float(z), float(angle)


@dataclass(frozen=True)
class Fit:
    """The scale and offset that fit a model to a capsule."""

    scale: float
    #: Where the model's origin goes, relative to the capsule's base.
    translation: tuple[float, float, float]

    def place(self, node: Any) -> None:
        """Set a ``Transform``'s scale and translation to this fit."""
        node.scale = (self.scale,) * 3
        node.translation = self.translation


def fit_to_height(minimum: Any, maximum: Any, height: float, base: float = 0.0
                  ) -> Fit:
    """The fit that makes a model with these bounds ``height`` tall.

    The model is scaled uniformly and moved up so the lowest point of the model
    is at ``base``, the height of the capsule's base. Bounds with no height
    (flat, inverted or not finite) and a capsule with none leave the model
    as it is.
    """
    low = float(np.asarray(minimum, 'd').reshape(-1)[1])
    high = float(np.asarray(maximum, 'd').reshape(-1)[1])
    size = high - low
    if not (math.isfinite(size) and size > 0.0 and height > 0.0):
        return Fit(1.0, (0.0, 0.0, 0.0))
    scale = float(height) / size
    return Fit(scale, (0.0, float(base) - low * scale, 0.0))


def model_bounds(model: Any) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """The corners of a model's vertices in its rest pose, or None with no triangles."""
    from OpenGLContext.scenegraph.meshdata import merged_arrays
    found = merged_arrays([model.group])
    if found is None:
        return None
    points = found.attributes['POSITION']
    return points.min(axis=0), points.max(axis=0)
