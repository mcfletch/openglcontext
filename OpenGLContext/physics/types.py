"""The values the physics service takes and returns: materials, filters, characters' settings, poses.

These are the package's own classes. The engine converts them to its own at
its boundary (:mod:`OpenGLContext.physics.joltengine`), so a game written
against them names no engine's types. The field
names of :class:`Material`, :class:`CollisionFilter` and
:class:`CharacterCapabilities` are those of the OMI glTF physics extensions,
since a glTF document carries them by those names.
"""
from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body

__all__ = ['COMBINES', 'CharacterCapabilities', 'CharacterState', 'CollisionFilter', 'EngineInfo',
           'GravityZone', 'Hit', 'Material', 'Poses', 'WorldCounts']

#: How the coefficients of two touching surfaces are combined into one.
COMBINES = ('average', 'minimum', 'maximum', 'multiply')


_Coercible = TypeVar('_Coercible', bound='_Coerced')


class _Coerced:
    """A dataclass that copies itself from any object with the same field names."""

    def _values(self) -> tuple[Any, ...]:
        return tuple(getattr(self, name) for name in getattr(self, '__dataclass_fields__', {}))

    def _same(self, other: object) -> bool | None:
        """Whether ``other``, of this class or another with every one of its fields, has its values."""
        names: Iterable[str] = getattr(self, '__dataclass_fields__', {})
        if not all(hasattr(other, name) for name in names):
            return None
        return all(getattr(self, name) == getattr(other, name) for name in names)

    @classmethod
    def coerce(cls: type[_Coercible], value: Any) -> _Coercible:
        """``value`` as this class: itself, the defaults for None, else a copy of the same-named attributes.

        Raises TypeError for an object that has none of the fields.
        """
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        names: Iterable[str] = getattr(cls, '__dataclass_fields__', {})
        found = {name: getattr(value, name) for name in names if hasattr(value, name)}
        if not found:
            raise TypeError('%r has none of the fields of %s' % (value, cls.__name__))
        return cls(**found)


@dataclass(frozen=True, slots=True, eq=False)
class Material(_Coerced):
    """How a surface grips and bounces.

    ``staticFriction`` and ``dynamicFriction`` are Coulomb coefficients, at
    rest and sliding. ``restitution`` is the fraction of the closing speed a
    bounce keeps, 0 to 1. ``frictionCombine`` and ``restitutionCombine`` say
    how two touching surfaces' values make the pair's, one of :data:`COMBINES`.
    """
    staticFriction: float = 0.6
    dynamicFriction: float = 0.6
    restitution: float = 0.0
    frictionCombine: str = 'average'
    restitutionCombine: str = 'average'

    def __eq__(self, other: object) -> bool:
        """Equal to a material, this package's or an engine's, with the same values."""
        same = self._same(other)
        return NotImplemented if same is None else same

    def __hash__(self) -> int:
        return hash(self._values())


@dataclass(frozen=True, slots=True, eq=False)
class CollisionFilter(_Coerced):
    """Which bodies a body collides with, by named systems.

    A body is a member of each system in ``collisionSystems``. It collides
    with another where neither names a system of the other in
    ``notCollideWithSystems`` and each, where its ``collideWithSystems`` is
    not None, names a system of the other there. None collides with every
    system not excluded.
    """
    collisionSystems: tuple[str, ...] = ()
    collideWithSystems: tuple[str, ...] | None = None
    notCollideWithSystems: tuple[str, ...] = ()

    def __eq__(self, other: object) -> bool:
        """Equal to a filter, this package's or an engine's, with the same systems."""
        same = self._same(other)
        return NotImplemented if same is None else same

    def __hash__(self) -> int:
        return hash(self._values())

    def collides_with(self, other: CollisionFilter) -> bool:
        """Whether bodies with this filter and ``other`` collide; each must allow the other."""
        return _admits(self, other) and _admits(other, self)


def _admits(one: CollisionFilter, other: CollisionFilter) -> bool:
    systems = set(other.collisionSystems)
    if systems & set(one.notCollideWithSystems):
        return False
    return one.collideWithSystems is None or bool(systems & set(one.collideWithSystems))


class CharacterState(enum.Enum):
    """What a character is doing.

    The first that holds, in this order: ``FLYING``, ``SWIMMING``, ``DOWN``
    (knocked down), ``AIRBORNE`` (off the ground), ``SLIDING``, ``CROUCHING``,
    ``STANDING``.
    """
    STANDING = 'standing'
    CROUCHING = 'crouching'
    SLIDING = 'sliding'
    AIRBORNE = 'airborne'
    DOWN = 'down'
    SWIMMING = 'swimming'
    FLYING = 'flying'

    def __eq__(self, other: object) -> bool:
        """Equal to a member of another ``CharacterState`` enumeration (an engine's) with the same value."""
        if isinstance(other, enum.Enum) and type(other).__name__ == 'CharacterState':
            return bool(self.value == other.value)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._name_)


@dataclass(slots=True)
class CharacterCapabilities(_Coerced):
    """A walker's capsule, speeds and limits.

    Speeds are in metres a second, heights, radius and ``stepHeight`` in
    metres, ``maxSlope`` in degrees, times in seconds and masses in
    kilograms. ``swimDrag`` and ``pushFriction`` are per second: how fast
    water bleeds off a swimmer's vertical speed, and how fast a push's speed
    falls away on the ground. ``airControl`` is the fraction of steering kept
    off the ground. ``terminalVelocity`` caps a fall (0 for no cap).
    ``coyoteTime`` is how long after walking off an edge a jump is still
    taken, and ``jumpBuffer`` how long a jump asked for in the air is kept
    for the landing. ``mass`` divides a blow's impulse into a change of
    velocity; ``pushMass`` is the heaviest dynamic body the character moves by
    walking into it, at up to ``pushSpeed`` (None: ``walkSpeed``).
    """
    walkSpeed: float = 3.0
    runSpeed: float = 6.0
    sprintSpeed: float = 9.0
    crouchSpeed: float = 1.5
    canSprint: bool = True
    canCrouch: bool = True
    canJump: bool = True
    canFly: bool = True
    flySpeed: float = 8.0
    swimSpeed: float = 2.0
    swimDrag: float = 4.0
    jumpHeight: float = 1.2
    jumpFollowsSlope: bool = False
    stepHeight: float = 0.35
    maxSlope: float = 50.0
    eyeHeight: float = 1.6
    standHeight: float = 1.8
    crouchHeight: float = 1.0
    radius: float = 0.3
    airControl: float = 0.4
    pushFriction: float = 6.0
    terminalVelocity: float = 55.0
    suppressOverVoid: bool = False
    coyoteTime: float = 0.12
    jumpBuffer: float = 0.12
    mass: float = 80.0
    pushMass: float = 200.0
    pushSpeed: float | None = None


@dataclass(frozen=True, slots=True)
class EngineInfo:
    """The engine that steps a world: its name, version, step rate and floating-point precision.

    ``tick_hz`` is in steps a second; ``precision`` is ``'single'`` or
    ``'double'``.
    """
    name: str
    version: str
    tick_hz: float
    precision: str

    def __str__(self) -> str:
        return '%s %s %s' % (self.name, self.version, self.precision)


@dataclass(frozen=True, slots=True)
class WorldCounts:
    """How many bodies the world holds and how many pairs of them touch, as of its last step.

    ``bodies`` counts every body in the world, characters' bodies included;
    ``contacts`` counts the touching pairs the step found.
    """
    bodies: int
    contacts: int


@dataclass(frozen=True, slots=True)
class Poses:
    """Bodies' poses and motion as arrays, a row for each body asked for, in the order asked.

    ``uids`` are the bodies' :attr:`~OpenGLContext.physics.body.Body.uid`;
    ``position`` is ``(n, 3)`` metres, ``orientation`` ``(n, 4)`` unit
    quaternions ``(x, y, z, w)``, ``velocity`` ``(n, 3)`` metres a second and
    ``angular_velocity`` ``(n, 3)`` radians a second about the world axes.
    ``mass`` is kilograms, 0 for a body that is not dynamic; ``asleep`` is
    whether the world has put a dynamic body to sleep.
    """
    uids: np.ndarray
    position: np.ndarray
    orientation: np.ndarray
    velocity: np.ndarray
    angular_velocity: np.ndarray
    mass: np.ndarray
    asleep: np.ndarray

    def __len__(self) -> int:
        return len(self.uids)

    @classmethod
    def empty(cls) -> Poses:
        """No bodies."""
        return cls(np.zeros(0, dtype='i8'), np.zeros((0, 3)), np.zeros((0, 4)), np.zeros((0, 3)),
                   np.zeros((0, 3)), np.zeros(0), np.zeros(0, dtype=bool))


@dataclass(frozen=True, slots=True)
class GravityZone:
    """A change of gravity inside a region, as :meth:`Physics.add_gravity_zone` made it.

    ``region`` is a :class:`~OpenGLContext.physics.zones.Box` or
    :class:`~OpenGLContext.physics.zones.Sphere`. ``gravity`` is the
    acceleration in metres a second squared: along ``direction``, or toward
    the point ``toward`` where that is given. A higher ``priority`` wins;
    ``replace`` drops the lower ones instead of adding to them and ``stop``
    ends the counting at this zone.
    """
    region: Any
    gravity: float
    direction: tuple[float, float, float] = (0.0, -1.0, 0.0)
    toward: tuple[float, ...] | None = None
    priority: int = 0
    replace: bool = False
    stop: bool = False
    #: Distinguishes this zone from another of equal values.
    uid: int = field(default=0, compare=False)


@dataclass(frozen=True, slots=True)
class Hit:
    """What a ray met: the body, the point, the surface normal there and how far along it was.

    ``triangle`` is the number of the triangle struck, or -1 for a shape that
    has none. ``body`` is None for a body the service has no handle for.
    """
    body: Body | None
    point: np.ndarray
    normal: np.ndarray
    distance: float
    triangle: int


def float_tuple(values: Iterable[Any]) -> tuple[float, ...]:
    """``values`` as a tuple of floats."""
    return tuple(float(v) for v in values)
