"""Joints: bodies held to each other or to the world.

The service makes them (:meth:`~OpenGLContext.physics.service.Physics.add_hinge`
and its siblings) and returns a :class:`Joint` handle::

    door = physics.add_hinge(panel, frame, anchor=(0, 1, 0), axis=(0, 1, 0),
                             limits=(0.0, 1.6))
    wheel = physics.add_hinge(rotor, anchor=(6, 4, 0), axis=(0, 1, 0), motor=(4.0, 30.0))
    wheel.drive(-4.0, 30.0)
    print(door.angle)

The kinds are in :data:`KINDS`: a hinge turns about one axis, a ball about a
point, a slider moves along one axis, a distance keeps two points apart, a
universal joint carries a spin across two axes at an angle, a wheel turns about
its axle and steers about a second axis on a spring, and a motor turns two
bodies against each other about up to three axes.

Anchors and axes are world coordinates where the bodies stand when the joint is
made; each body carries them from then on. ``to=None`` is the world. A joint
travels to the world as a :class:`JointSpec`, plain data in a command, so it
works the same whichever thread steps the world.

The bodies of a joint do not collide with each other unless ``collide=True``.
Removing either body removes its joints.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['KINDS', 'Joint', 'JointSpec', 'make_joint']

#: The kinds of joint the service makes.
KINDS = ('hinge', 'ball', 'slider', 'distance', 'universal', 'wheel', 'motor')
#: The kinds whose :attr:`Joint.angles` are read, and what each reading is.
READINGS = {'hinge': ('angle',), 'slider': ('position',), 'wheel': ('steering', 'spin'),
            'motor': ('angle',)}

_ids = itertools.count(1)

Vector = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class JointSpec:
    """What a joint is, in plain data the worker builds the constraint from.

    ``body`` and ``to`` are body ids, ``to`` 0 for the world. ``anchor`` is a
    world point: the pivot, or the end of a distance on ``body``.
    ``to_anchor`` is the distance's other end. ``axis`` is the hinge's,
    slider's or universal joint's first direction and a wheel's steering axis;
    ``to_axis`` is the universal joint's second direction and a wheel's axle.
    ``lower`` and ``upper`` stop the angle in radians, a wheel's steering or
    the slide in metres; ``speed`` and ``force`` drive the motor in radians or
    metres a second, with at most that torque in newton-metres or force in
    newtons. A wheel's ``speed`` and ``force`` drive its axle and
    ``steer_speed`` and ``steer_force`` its steering; ``stiffness`` in newtons
    a metre and ``damping`` in newton-seconds a metre spring its anchor along
    the steering axis. A motor joint turns about ``axes`` with ``torques`` in
    newton-metres.
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
    to_axis: Vector | None = None
    steer_speed: float = 0.0
    steer_force: float = 0.0
    stiffness: float = 0.0
    damping: float = 0.0
    axes: tuple[Vector, ...] = ()
    torques: tuple[float, ...] = ()


class Joint:
    """A joint in a world: what it holds, its motor, its readings and a call to take it out."""

    def __init__(self, physics: Physics, kind: str, body: Body, to: Body | None,
                 spec: JointSpec) -> None:
        self.physics = physics
        #: Distinguishes this joint from every other the process makes.
        self.uid = next(_ids)
        #: One of :data:`KINDS`.
        self.kind = kind
        self.body = body
        #: The body ``body`` is held to; None for the world.
        self.to = to
        self.spec = spec
        #: The motor's speed and force, as made or as :meth:`drive` last set them; a wheel's axle motor.
        self.motor = (spec.speed, spec.force)
        #: A motor joint's torques about its axes, in newton-metres.
        self.torques = spec.torques
        self._removed = False
        #: Whether the world has been asked to publish this joint's readings.
        self._watched = False

    def __repr__(self) -> str:
        return 'Joint(%s, %r, to=%r)' % (self.kind, self.body, self.to)

    @property
    def alive(self) -> bool:
        """Whether the joint is in the world: not removed, and neither body removed."""
        return not self._removed and self.body.alive and (self.to is None or self.to.alive)

    # -- readings ---------------------------------------------------------
    @property
    def angles(self) -> tuple[float, ...]:
        """What the joint reads now: a hinge's angle, a wheel's steering and spin, a motor's angle about each axis.

        Angles are in radians from where the joint started; a slider reads its
        slide in metres. The first read asks the world to publish them and
        waits for its answer; with the world on its own thread later reads are
        at most a tick old. Raises AttributeError for a joint that has no reading.
        """
        if self.kind not in READINGS:
            raise AttributeError('a %s joint has no angle or position to read' % self.kind)
        return self.physics._joint_reading(self)

    @property
    def angle(self) -> float:
        """A hinge's angle, a wheel's steering angle or a motor's angle about its first axis, in radians."""
        if self.kind == 'slider':
            raise AttributeError('a slider has a position, not an angle')
        return self.angles[0]

    @property
    def position(self) -> float:
        """How far a slider has slid along its axis since it was made, in metres."""
        if self.kind != 'slider':
            raise AttributeError('a %s joint has no position; a slider has' % self.kind)
        return self.angles[0]

    # -- commands ---------------------------------------------------------
    def drive(self, speed: float = 0.0, force: float = 0.0, *,
              torques: Iterable[float] | None = None) -> None:
        """Run the motor at ``speed`` with at most ``force``, or a motor joint with ``torques``.

        A hinge's or wheel axle's speed is in radians a second and its force a
        torque in newton-metres; a slider's is in metres a second and newtons.
        A speed of 0 with a force holds the joint still; a force of 0 switches
        the motor off. A motor joint takes ``torques``, one in newton-metres
        for each of its axes.
        """
        if self.kind == 'motor':
            given = tuple(float(v) for v in (torques if torques is not None else ()))
            if len(given) != len(self.spec.axes):
                raise ValueError('a motor joint with %d axes takes %d torques, not %r'
                                 % (len(self.spec.axes), len(self.spec.axes), given))
            self.torques = given
            if self.alive:
                self.physics._command('joint_torques', self.body, self.uid, given)
            return
        self.motor = (float(speed), float(force))
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


def _axis(value: Any, name: str = 'axis') -> Vector:
    axis = _vector(value, name)
    if math.hypot(*axis) < 1e-9:
        raise ValueError('%s must have a direction, not %r' % (name, value))
    return axis


def _apart(first: Vector, second: Vector, names: str) -> None:
    """Raise ValueError where two axes lie along one line."""
    cross = (first[1] * second[2] - first[2] * second[1], first[2] * second[0] - first[0] * second[2],
             first[0] * second[1] - first[1] * second[0])
    if math.hypot(*cross) < 1e-6 * math.hypot(*first) * math.hypot(*second):
        raise ValueError('%s must not lie along one line' % names)


def _body(physics: Physics, value: Any, name: str) -> Body:
    from OpenGLContext.physics.body import Body  # noqa: PLC0415 body imports the service's types

    found = value if isinstance(value, Body) else physics.body_for(value)
    if found is None:
        raise ValueError('%s has no body in this world: add it first' % (name,))
    if not found.alive:
        raise ValueError('%s %r has been removed' % (name, found))
    return found


def _motor(value: Any) -> tuple[float, float]:
    if value is None:
        return 0.0, 0.0
    speed, force = (float(v) for v in value)
    return speed, force


def make_joint(physics: Physics, kind: str, body: Any, to: Any = None, *,
               anchor: Iterable[float] | None = None,
               to_anchor: Iterable[float] | None = None,
               axis: Iterable[float] | None = None,
               to_axis: Iterable[float] | None = None,
               limits: Iterable[float] | None = None,
               motor: Iterable[float] | None = None,
               steering_motor: Iterable[float] | None = None,
               suspension: Iterable[float] | None = None,
               axes: Iterable[Iterable[float]] | None = None,
               torques: Iterable[float] | None = None,
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
    speed, force = _motor(motor)
    to_uid = 0 if other is None else other.uid
    if kind == 'distance':
        point = _vector(held.position if anchor is None else anchor, 'anchor')
        if to_anchor is None and other is None:
            raise ValueError('a distance to the world needs to_anchor, the point it is held to')
        far = _vector(other.position if to_anchor is None and other is not None
                      else to_anchor, 'to_anchor')
        spec = JointSpec(kind, held.uid, to_uid, anchor=point, to_anchor=far,
                         length=None if length is None else float(length), collide=collide)
    elif kind == 'motor':
        directions = tuple(_axis(one, 'axes') for one in (axes or ()))
        amounts = tuple(float(v) for v in (torques or ()))
        if not 1 <= len(directions) <= 3:
            raise ValueError('a motor joint turns about one to three axes, not %d' % len(directions))
        if len(amounts) != len(directions):
            raise ValueError('a motor joint takes a torque for each axis: %d axes, %d torques'
                             % (len(directions), len(amounts)))
        spec = JointSpec(kind, held.uid, to_uid, axes=directions, torques=amounts,
                         collide=collide)
    elif kind in ('universal', 'wheel'):
        if anchor is None:
            raise ValueError('a %s needs anchor, the world point it turns about' % kind)
        first = _axis(axis, 'axis' if kind == 'universal' else 'steering_axis')
        second = _axis(to_axis, 'to_axis' if kind == 'universal' else 'axle')
        _apart(first, second, 'the two axes')
        steer_speed, steer_force = _motor(steering_motor)
        stiffness, damping = (float(v) for v in suspension) if suspension is not None else (0.0, 0.0)
        if stiffness < 0.0 or damping < 0.0:
            raise ValueError('suspension is (stiffness, damping), neither below zero, not %r'
                             % (suspension,))
        spec = JointSpec(kind, held.uid, to_uid, anchor=_vector(anchor, 'anchor'), axis=first,
                         to_axis=second, lower=stops[0], upper=stops[1], speed=speed,
                         force=force, steer_speed=steer_speed, steer_force=steer_force,
                         stiffness=stiffness, damping=damping, collide=collide)
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
        spec = JointSpec(kind, held.uid, to_uid, anchor=point, axis=direction, lower=stops[0],
                         upper=stops[1], speed=speed, force=force, collide=collide)
    joint = Joint(physics, kind, held, other, spec)
    physics._command('joint', held, joint.uid, spec)
    return joint
