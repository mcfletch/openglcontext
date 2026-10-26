"""Joints: bodies held to each other or to the world by a hinge, a ball, a slider or a distance.

The service makes them (:meth:`~OpenGLContext.physics.service.Physics.add_hinge`
and its siblings) and returns a :class:`Joint` handle::

    door = physics.add_hinge(panel, frame, anchor=(0, 1, 0), axis=(0, 1, 0),
                             limits=(0.0, 1.6))
    wheel = physics.add_hinge(rotor, anchor=(6, 4, 0), axis=(0, 1, 0), motor=(4.0, 30.0))
    wheel.drive(-4.0, 30.0)

Anchors and axes are world coordinates where the bodies stand when the joint is
made; each body carries them from then on. ``to=None`` is the world. A joint
travels to the world as a :class:`JointSpec`, plain data in a command, so it
works the same whichever thread steps the world. :class:`JointTable` is the
worker's side: the omi_physics constraint of each joint, made from its spec
where the bodies are when the command is applied.

The bodies of a joint do not collide with each other unless ``collide=True``.
Removing either body removes its joints.
"""
from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import mathutil
from omi_physics.joints import BallJoint, DistanceConstraint, HingeJoint, SliderJoint

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['KINDS', 'Joint', 'JointSpec', 'JointTable', 'make_joint']

log = logging.getLogger(__name__)

#: The kinds of joint the service makes.
KINDS = ('hinge', 'ball', 'slider', 'distance')

_ids = itertools.count(1)

Vector = tuple[float, float, float]
_ORIGIN: Vector = (0.0, 0.0, 0.0)
_UP: Vector = (0.0, 1.0, 0.0)


@dataclass(frozen=True, slots=True)
class JointSpec:
    """What a joint is, in plain data the worker builds the constraint from.

    ``body`` and ``to`` are body ids, ``to`` 0 for the world. ``anchor`` is a
    world point: the hinge's or ball's pivot, or the end of a distance on
    ``body``. ``to_anchor`` is the distance's other end. ``axis`` is the hinge's
    or slider's direction. ``lower`` and ``upper`` stop the angle in radians or
    the slide in metres; ``speed`` and ``force`` drive the motor in radians or
    metres a second, with at most that torque in newton-metres or force in newtons.
    """
    kind: str
    body: int
    to: int
    anchor: Vector | None = None
    to_anchor: Vector | None = None
    axis: Vector | None = None
    lower: float = -math.inf
    upper: float = math.inf
    speed: float = 0.0
    force: float = 0.0
    length: float | None = None
    collide: bool = False

    def build(self, world: PhysicsWorld, body: int, to: int) -> Any:
        """The omi_physics constraint for this joint between world slots ``body`` and ``to`` (-1, the world)."""
        anchor, axis = self.anchor or _ORIGIN, self.axis or _UP
        if self.kind == 'hinge':
            made: Any = HingeJoint(to, body, anchor, axis, lower=self.lower, upper=self.upper,
                                   motor_speed=self.speed, motor_torque=self.force)
        elif self.kind == 'ball':
            made = BallJoint(to, body, anchor)
        elif self.kind == 'slider':
            made = SliderJoint(to, body, axis, lower=self.lower, upper=self.upper,
                               motor_speed=self.speed, motor_force=self.force)
        else:
            made = DistanceConstraint(to, body, _local(world, to, self.to_anchor or _ORIGIN),
                                      _local(world, body, anchor), length=self.length)
        made.collide_connected = self.collide
        return made


def _local(world: PhysicsWorld, slot: int, point: Vector) -> np.ndarray:
    """``point`` in the frame of the body in ``slot``; the world's own frame for -1."""
    at = np.asarray(point, dtype='d')
    if slot < 0:
        return at
    turn = mathutil.quat_to_matrix(np.asarray(world.orientation[slot], dtype='d'))
    return np.asarray(turn.T @ (at - np.asarray(world.position[slot], dtype='d')))


class JointTable:
    """The worker's joints: each joint's constraint in the world, by joint id."""

    def __init__(self) -> None:
        self._held: dict[int, tuple[Any, int, int]] = {}

    def __len__(self) -> int:
        return len(self._held)

    def add(self, world: PhysicsWorld, joint: int, spec: JointSpec, body: int | None,
            to: int | None) -> None:
        """Make joint ``joint`` from ``spec`` between world slots ``body`` and ``to`` (-1, the world).

        A slot of None is a body that has left the world, and the joint is not made.
        """
        if body is None or to is None:
            log.warning('joint %d names a body that has left the world; it is not made', joint)
            return
        made = world.add_joint_constraint(spec.build(world, body, to))
        self._held[joint] = (made, spec.body, spec.to)

    def remove(self, world: PhysicsWorld, joint: int) -> None:
        """Take joint ``joint`` out of the world; one that is not there is ignored."""
        held = self._held.pop(joint, None)
        if held is not None:
            world.remove_joint_constraint(held[0])
            for slot in (getattr(held[0], 'a', -1), getattr(held[0], 'b', -1)):
                if slot >= 0:
                    world.wake(slot)

    def motor(self, world: PhysicsWorld, joint: int, speed: float, force: float) -> None:
        """Give joint ``joint``'s motor a new speed and limit, and wake its bodies."""
        held = self._held.get(joint)
        if held is None:
            return
        made = held[0]
        made.motor_speed = float(speed)
        if isinstance(made, SliderJoint):
            made.motor_force = float(force)
        else:
            made.motor_torque = float(force)
        for slot in (made.a, made.b):
            if slot >= 0:
                world.wake(slot)

    def forget_body(self, world: PhysicsWorld, body: int) -> None:
        """Remove the joints of body id ``body``, which is leaving the world."""
        for joint in [joint for joint, held in self._held.items() if body in held[1:]]:
            self.remove(world, joint)


class Joint:
    """A joint in a world: what it holds, its motor, and a call to take it out."""

    def __init__(self, physics: Physics, kind: str, body: Body, to: Body | None,
                 spec: JointSpec) -> None:
        self.physics = physics
        #: Distinguishes this joint from every other the process makes.
        self.uid = next(_ids)
        self.kind = kind
        self.body = body
        #: The body ``body`` is held to; None for the world.
        self.to = to
        self.spec = spec
        self._removed = False

    def __repr__(self) -> str:
        return 'Joint(%s, %r, to=%r)' % (self.kind, self.body, self.to)

    @property
    def alive(self) -> bool:
        """Whether the joint is in the world: not removed, and neither body removed."""
        return not self._removed and self.body.alive and (self.to is None or self.to.alive)

    def drive(self, speed: float, force: float) -> None:
        """Run the motor at ``speed`` with at most ``force``.

        A hinge's speed is in radians a second and its force a torque in
        newton-metres; a slider's is in metres a second and newtons. A speed of
        0 with a force holds the joint still; a force of 0 switches the motor off.
        """
        if self.alive:
            self.physics._command('joint_motor', self.body, self.uid, float(speed), float(force))

    def remove(self) -> None:
        """Take the joint out of the world. Removing twice is harmless."""
        if self.alive:
            self.physics._command('unjoint', self.body, self.uid)
        self._removed = True


def _pair(value: Any, name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    low, high = (float(v) for v in value)
    if not low <= high:
        raise ValueError('%s must be (lower, upper) with lower <= upper, not %r' % (name, value))
    return low, high


def _vector(value: Any, name: str) -> Vector:
    x, y, z = (float(v) for v in value)
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise ValueError('%s must be finite, not %r' % (name, value))
    return (x, y, z)


def _axis(value: Any) -> Vector:
    axis = _vector(value, 'axis')
    if math.hypot(*axis) < 1e-9:
        raise ValueError('axis must have a direction, not %r' % (value,))
    return axis


def _body(physics: Physics, value: Any, name: str) -> Body:
    from OpenGLContext.physics.body import Body  # noqa: PLC0415 body imports the service's types

    found = value if isinstance(value, Body) else physics.body_for(value)
    if found is None:
        raise ValueError('%s has no body in this world: add it first' % (name,))
    if not found.alive:
        raise ValueError('%s %r has been removed' % (name, found))
    return found


def make_joint(physics: Physics, kind: str, body: Any, to: Any = None, *,
               anchor: Iterable[float] | None = None,
               to_anchor: Iterable[float] | None = None,
               axis: Iterable[float] | None = None,
               limits: Iterable[float] | None = None,
               motor: Iterable[float] | None = None,
               length: float | None = None, collide: bool = False) -> Joint:
    """A joint of ``kind`` holding ``body`` to ``to`` (None, the world), sent to the world."""
    held = _body(physics, body, 'body')
    other = None if to is None else _body(physics, to, 'to')
    if other is not None and other._pending:
        raise ValueError('%r is scenery still being cooked: call physics.wait_cooked() first'
                         % (other,))
    if other is held:
        raise ValueError('a joint holds a body to another body or to the world, not to itself')
    stops = _pair(limits, 'limits') or (-math.inf, math.inf)
    speed, force = (float(v) for v in motor) if motor is not None else (0.0, 0.0)
    if kind == 'distance':
        point = _vector(held.position if anchor is None else anchor, 'anchor')
        if to_anchor is None and other is None:
            raise ValueError('a distance to the world needs to_anchor, the point it is held to')
        far = _vector(other.position if to_anchor is None and other is not None
                      else to_anchor, 'to_anchor')
        spec = JointSpec(kind, held.uid, 0 if other is None else other.uid, anchor=point,
                         to_anchor=far, length=None if length is None else float(length),
                         collide=collide)
    else:
        if kind == 'slider':
            point = None
        else:
            if anchor is None:
                raise ValueError('a %s needs anchor, the world point it turns about' % kind)
            point = _vector(anchor, 'anchor')
        direction = _axis(axis) if kind in ('hinge', 'slider') else None
        if direction is None and axis is not None:
            raise ValueError('a %s has no axis' % kind)
        spec = JointSpec(kind, held.uid, 0 if other is None else other.uid, anchor=point,
                         axis=direction, lower=stops[0], upper=stops[1], speed=speed,
                         force=force, collide=collide)
    joint = Joint(physics, kind, held, other, spec)
    physics._command('joint', held, joint.uid, spec)
    return joint
