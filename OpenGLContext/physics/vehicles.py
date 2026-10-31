"""Vehicles: a dynamic chassis on wheels, driven by a throttle, a steer, a brake and a handbrake.

:meth:`Physics.add_vehicle <OpenGLContext.physics.service.Physics.add_vehicle>`
takes a dynamic :class:`~OpenGLContext.physics.body.Body` (the chassis) and a
:class:`VehicleSettings`, and returns a :class:`Vehicle`. The engine casts the
wheels, springs the suspension and drives the tyres on its world thread every
tick; the game sends inputs and reads the result.

The settings are plain data in SI units and the chassis's own frame:
:class:`Wheel` for each wheel, with :class:`VehicleEngine`,
:class:`Transmission`, :class:`Differential`, :class:`AntiRollBar`,
:class:`Track` and :class:`Lean` for the drivetrain. :meth:`VehicleSettings.as_dict`
and :meth:`VehicleSettings.from_dict` turn them to and from builtin types for a
file. :class:`CarTuning` and :func:`car_wheels` are a car stated in the
raycast vocabulary (forces in newtons, suspension in car weights per metre),
which :meth:`VehicleSettings.from_tuning` maps onto the settings.

Reads come from the newest tick the world has published: :meth:`Vehicle.state`
is a :class:`VehicleState` with a :class:`WheelState` per wheel. The chassis's
own pose is its body's, interpolated between ticks as every body's is.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

from OpenGLContext.physics.checks import number, vector

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.handlers import Handler
    from OpenGLContext.physics.service import Physics

__all__ = ['KINDS', 'TARMAC', 'WHEEL_CASTS', 'AntiRollBar', 'CarTuning', 'CarWheel', 'Differential',
           'Impact', 'Lean', 'Surface', 'Track', 'Transmission', 'Vehicle', 'VehicleEngine',
           'VehicleSettings', 'VehicleState', 'Wheel', 'WheelState', 'car_wheels']

#: The kinds of vehicle: wheels joined by differentials, a motorcycle that leans, and two tracks.
KINDS = ('wheeled', 'motorcycle', 'tracked')
#: How a wheel finds the ground: a ray from its mount, or a sphere or cylinder of its size swept down.
WHEEL_CASTS = ('ray', 'sphere', 'cylinder')

Vector = tuple[float, float, float]
Curve = tuple[tuple[float, float], ...]


@dataclasses.dataclass(frozen=True)
class Wheel:
    """One wheel, in the chassis's own frame.

    ``position`` is where the suspension is mounted. The wheel's centre hangs
    between ``suspension_min`` and ``suspension_max`` metres below it, and the
    tyre meets the ground ``radius`` below that; the spring's natural length
    is ``suspension_max + preload``. ``stiffness`` (N/m) and ``damping``
    (N s/m) are the spring's. A ``steered`` wheel turns to
    :attr:`VehicleSettings.max_steer`; a ``driven`` wheel takes the engine's
    torque. ``brake_torque`` and ``handbrake_torque`` (N m) are the most each
    pedal holds the wheel with. ``inertia`` (kg m2) and ``angular_damping``
    (1/s) are the wheel's own. ``grip`` multiplies the tyre curves at this
    wheel. ``track`` is 0 (left) or 1 (right) on a tracked vehicle, -1
    elsewhere.
    """
    position: Vector
    radius: float = 0.3
    width: float = 0.2
    suspension_min: float = 0.0
    suspension_max: float = 0.3
    preload: float = 0.0
    stiffness: float = 30000.0
    damping: float = 3000.0
    steered: bool = False
    driven: bool = True
    brake_torque: float = 1500.0
    handbrake_torque: float = 0.0
    inertia: float = 0.9
    angular_damping: float = 0.2
    grip: float = 1.0
    track: int = -1


@dataclasses.dataclass(frozen=True)
class VehicleEngine:
    """The motor: ``max_torque`` (N m) scaled by ``torque_curve`` between ``min_rpm`` and ``max_rpm``.

    ``torque_curve`` is (rpm over ``max_rpm``, fraction of ``max_torque``)
    points; there is no torque above ``max_rpm``. ``inertia`` (kg m2) and
    ``damping`` (1/s) are the motor's own.
    """
    max_torque: float = 500.0
    min_rpm: float = 1000.0
    max_rpm: float = 6000.0
    torque_curve: Curve = ((0.0, 0.8), (0.66, 1.0), (1.0, 0.8))
    inertia: float = 0.5
    damping: float = 0.2


@dataclasses.dataclass(frozen=True)
class Transmission:
    """The gearbox: ratios of motor speed to output speed, and when an automatic one shifts.

    An ``automatic`` box shifts up past ``shift_up_rpm`` and down below
    ``shift_down_rpm``, spending ``switch_time`` seconds with no drive and
    ``clutch_release_time`` engaging, then ``switch_latency`` before the next
    shift. ``clutch_strength`` (kg m2/s) is the torque the engaged clutch
    passes per rad/s of slip. A negative throttle selects reverse.
    """
    automatic: bool = True
    gears: tuple[float, ...] = (2.66, 1.78, 1.3, 1.0, 0.74)
    reverse_gears: tuple[float, ...] = (-2.90,)
    switch_time: float = 0.5
    clutch_release_time: float = 0.3
    switch_latency: float = 0.5
    shift_up_rpm: float = 4000.0
    shift_down_rpm: float = 2000.0
    clutch_strength: float = 10.0


@dataclasses.dataclass(frozen=True)
class Differential:
    """The motor's torque to a pair of wheels (indices into the wheels; -1 for none on that side).

    ``ratio`` is gearbox speed over wheel speed and ``split`` the right
    wheel's share. Past ``limited_slip`` (fastest over slowest wheel speed;
    ``inf`` for an open differential) the torque goes to the slower wheel.
    ``torque_ratio`` is this differential's share of the motor; a vehicle's
    shares add to 1.
    """
    left: int
    right: int
    ratio: float = 3.42
    split: float = 0.5
    limited_slip: float = 1.4
    torque_ratio: float = 1.0


@dataclasses.dataclass(frozen=True)
class AntiRollBar:
    """A bar between two wheels pushing their suspension lengths together with ``stiffness`` N/m."""
    left: int
    right: int
    stiffness: float = 1000.0


@dataclasses.dataclass(frozen=True)
class Track:
    """One track of a tracked vehicle; its wheels are those whose ``track`` names this side.

    ``driven_wheel`` takes the motor through ``ratio``; ``inertia`` (kg m2)
    and ``damping`` (1/s) are the track's; ``brake_torque`` (N m) brakes the
    driven wheel.
    """
    driven_wheel: int
    inertia: float = 10.0
    damping: float = 0.5
    brake_torque: float = 15000.0
    ratio: float = 6.0


@dataclasses.dataclass(frozen=True)
class Lean:
    """A motorcycle's lean: a spring (N m/rad) and damper (N m s/rad) toward the lean a turn needs.

    ``max_angle`` (rad) also limits the steering at speed; ``integration``
    and ``integration_decay`` add an integral term; ``smoothing`` (0 to 1)
    filters the target lean.
    """
    max_angle: float = math.radians(45.0)
    spring: float = 5000.0
    damping: float = 1000.0
    integration: float = 0.0
    integration_decay: float = 4.0
    smoothing: float = 0.8


@dataclasses.dataclass(frozen=True)
class VehicleSettings:
    """A vehicle, in SI units and the chassis's own frame.

    ``kind`` is one of :data:`KINDS`. ``forward`` and ``up`` are the
    chassis's axes (-Z and +Y by default). ``cast`` is one of
    :data:`WHEEL_CASTS`, with ``cast_radius`` the sphere's (0 takes the
    smallest wheel's); ``max_slope`` (rad) is the steepest ground a wheel
    stands on, and ``max_pitch_roll`` (rad) holds the chassis within that
    angle of upright (pi leaves it free).

    Tyres: ``longitudinal_friction`` is (slip ratio, friction) points and
    ``lateral_friction`` (slip angle in degrees, friction) points, multiplied
    by each wheel's grip and by the surface under it, and with
    ``body_friction`` by the friction of the body under it as
    ``sqrt(curve * friction)``.

    Steering: the steered wheels turn to ``max_steer`` (rad) at rest, falling
    as ``max_steer / (1 + (v / steer_falloff_speed)**2)`` with speed ``v``
    (0: no falloff), at ``steer_rate`` rad/s (0: at once).

    Forces on the chassis each tick: ``drag`` (N at 1 m/s) against the
    velocity, rising with its square; ``downforce`` (N at 1 m/s) toward the
    ground while a wheel touches it, rising with the square of speed;
    ``rolling_resistance``, a fraction of each grounded wheel's load against
    its rolling above 0.15 m/s. A vehicle with no throttle and no brake that
    comes down to ``holding_speed`` (m/s) brakes with input ``holding`` (0 to
    1) until it is driven again.

    Blows: the heaviest contact on the chassis each tick is
    :meth:`Vehicle.impact`; one closing at ``impact_speed`` m/s or more is an
    ``'impact'`` event, at ``crash_speed`` or more a ``'crash'`` event.

    ``differentials`` None gives one open-ish differential per axle of driven
    wheels, with ``differential_ratio`` and ``differential_limited_slip``.
    ``tracks`` are a tracked vehicle's left and right; ``lean`` is a
    motorcycle's.
    """
    wheels: tuple[Wheel, ...]
    kind: str = 'wheeled'
    engine: VehicleEngine = VehicleEngine()
    transmission: Transmission = Transmission()
    differentials: tuple[Differential, ...] | None = None
    differential_ratio: float = 3.42
    differential_limited_slip: float = 1.4
    anti_roll_bars: tuple[AntiRollBar, ...] = ()
    tracks: tuple[Track, Track] | None = None
    lean: Lean = Lean()
    forward: Vector = (0.0, 0.0, -1.0)
    up: Vector = (0.0, 1.0, 0.0)
    cast: str = 'ray'
    cast_radius: float = 0.0
    max_slope: float = math.radians(80.0)
    max_pitch_roll: float = math.pi
    longitudinal_friction: Curve = ((0.0, 0.0), (0.06, 1.2), (0.2, 1.0))
    lateral_friction: Curve = ((0.0, 0.0), (3.0, 1.2), (20.0, 1.0))
    body_friction: bool = True
    max_steer: float = math.radians(30.0)
    steer_falloff_speed: float = 0.0
    steer_rate: float = 0.0
    drag: float = 0.0
    downforce: float = 0.0
    rolling_resistance: float = 0.0
    holding: float = 0.0
    holding_speed: float = 0.5
    impact_speed: float = 2.0
    crash_speed: float = 10.0

    def __post_init__(self) -> None:
        if not self.wheels:
            raise ValueError('a vehicle needs at least one wheel')
        if self.kind not in KINDS:
            raise ValueError('kind must be one of %s, not %r' % (', '.join(KINDS), self.kind))
        if self.cast not in WHEEL_CASTS:
            raise ValueError('cast must be one of %s, not %r' % (', '.join(WHEEL_CASTS), self.cast))
        if self.kind == 'tracked' and self.tracks is None:
            raise ValueError('a tracked vehicle names its two tracks')

    def wheelbase(self) -> float:
        """Front axle to rear axle along ``forward``, in metres: the steered wheels to the rest where some steer."""
        forward = np.asarray(self.forward, dtype='d')
        forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
        along = [float(np.dot(wheel.position, forward)) for wheel in self.wheels]
        steered = [at for at, wheel in zip(along, self.wheels, strict=True) if wheel.steered]
        rest = [at for at, wheel in zip(along, self.wheels, strict=True) if not wheel.steered]
        if steered and rest:
            return abs(sum(steered) / len(steered) - sum(rest) / len(rest))
        return max(along) - min(along)

    def steer_lock(self, speed: float) -> float:
        """How far the steered wheels may turn at ``speed`` m/s, in radians."""
        falloff = float(self.steer_falloff_speed)
        if falloff <= 0.0:
            return float(self.max_steer)
        share = abs(float(speed)) / falloff
        return float(self.max_steer) / (1.0 + share * share)

    def as_dict(self) -> dict[str, Any]:
        """The settings as builtin types (dicts, lists, numbers, strings and bools), for a file."""
        plain: dict[str, Any] = _plain(dataclasses.asdict(self))
        return plain

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> VehicleSettings:
        """The settings :meth:`as_dict` wrote; missing keys take their defaults."""
        given = dict(values)
        given['wheels'] = tuple(_made(Wheel, wheel) for wheel in given['wheels'])
        for key, kind in (('engine', VehicleEngine), ('transmission', Transmission),
                          ('lean', Lean)):
            if key in given:
                given[key] = _made(kind, given[key])
        if given.get('differentials') is not None:
            given['differentials'] = tuple(_made(Differential, d) for d in given['differentials'])
        if 'anti_roll_bars' in given:
            given['anti_roll_bars'] = tuple(_made(AntiRollBar, b) for b in given['anti_roll_bars'])
        if given.get('tracks') is not None:
            left, right = (_made(Track, track) for track in given['tracks'])
            given['tracks'] = (left, right)
        for key in ('forward', 'up'):
            if key in given:
                given[key] = _vector3(given[key])
        for key in ('longitudinal_friction', 'lateral_friction'):
            if key in given:
                given[key] = tuple((float(x), float(y)) for x, y in given[key])
        return cls(**given)

    @classmethod
    def from_tuning(cls, tuning: CarTuning, wheels: Sequence[CarWheel], mass: float,
                    gravity: float = 9.81, **changes: Any) -> VehicleSettings:
        """The settings of a car stated as a :class:`CarTuning` and its :class:`CarWheel` list.

        ``mass`` is the chassis's (kg) and ``gravity`` the world's (m/s2);
        ``changes`` replace fields of the result. The mapping, field by field:

        - A wheel's ``position``, ``radius`` and ``grip`` carry over;
          ``suspension_travel`` is ``suspension_max`` with ``suspension_min``
          0; ``suspension_stiffness`` s (car weights per metre) is
          ``s * mass * gravity`` N/m and ``suspension_damping`` z (a fraction
          of critical) is ``z * 2 sqrt(stiffness * mass / wheels)`` N s/m.
        - ``engine_force`` (N at the wheels) and ``base_speed`` are a
          one-gear electric drivetrain: torque ``engine_force * radius`` flat
          to ``base_speed`` and constant power above it, the motor's top speed
          three times the speed where that power meets ``drag``.
          ``reverse_fraction`` is the reverse gear. Open differentials share
          the torque equally between the driven wheels.
        - ``brake_force`` (N, shared by the braked wheels) is each braked
          wheel's ``brake_torque = brake_force / n * radius``; the unsteered
          braked wheels take as much again as a handbrake.
        - ``maximum_steer``, ``steer_falloff_speed`` and ``steer_speed`` are
          ``max_steer``, ``steer_falloff_speed`` and ``steer_rate =
          steer_speed * maximum_steer``.
        - ``rolling_resistance``, ``drag`` and ``downforce`` carry over;
          ``holding`` (N) is the brake input ``holding / brake_force``.
        - The tyres saturate at full grip: longitudinal friction 1 from a
          slip ratio of 0.05, lateral friction 1 from a slip angle of a tenth
          of a degree, times each wheel's grip and the surface; the friction
          of the body under a wheel is not used.
        """
        from pyjoltphysics import VehicleSettings as Mapped  # noqa: PLC0415 the mapping is pyjoltphysics'

        mapped = Mapped.from_raycast(tuning, list(wheels), float(mass), float(gravity))
        plain = mapped.as_dict()
        plain['kind'] = KINDS[int(plain['kind'])]
        plain['cast'] = WHEEL_CASTS[int(plain['cast'])]
        made = cls.from_dict(plain)
        return dataclasses.replace(made, **changes) if changes else made


def _made(kind: Any, values: Any) -> Any:
    """``values``, a ``kind`` or its fields as a mapping, as a ``kind``."""
    if isinstance(values, kind):
        return values
    given = dict(values)
    for field in dataclasses.fields(kind):
        item = given.get(field.name)
        if isinstance(item, list):
            given[field.name] = tuple(tuple(v) if isinstance(v, list) else v for v in item)
    return kind(**given)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _vector3(values: Iterable[float]) -> Vector:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


# -- a car in the raycast vocabulary -------------------------------------------

@dataclasses.dataclass
class CarWheel:
    """One wheel of a car as :class:`CarTuning` states it.

    ``position`` is the top of the suspension in the chassis's frame (-Z
    forward); the wheel hangs ``suspension_travel`` below it at full droop.
    ``suspension_stiffness`` is in multiples of the car's weight per metre of
    compression, and ``suspension_damping`` a fraction of critical damping,
    so a tuning keeps when the car's mass changes. ``grip`` multiplies the
    friction at this wheel.
    """
    position: Vector
    radius: float = 0.34
    suspension_travel: float = 0.30
    suspension_stiffness: float = 22.0
    suspension_damping: float = 0.45
    steering: bool = False
    driven: bool = True
    braked: bool = True
    grip: float = 1.6


@dataclasses.dataclass
class CarTuning:
    """What a car's pedals and wheel are worth, in newtons and radians.

    ``engine_force`` and ``brake_force`` are newtons at full pedal, shared by
    the wheels that take them; ``reverse_fraction`` is reverse's share of the
    engine. ``maximum_steer`` is the lock in radians at rest, halving at
    ``steer_falloff_speed`` m/s (:meth:`steer_lock`), and ``steer_speed`` is
    full lock's share reached a second. ``base_speed`` (m/s) is where constant
    force gives way to constant power (0: constant force throughout).
    ``drag`` and ``downforce`` are newtons at 1 m/s, rising with the square of
    the speed; ``rolling_resistance`` is a fraction of the car's weight.
    ``holding`` (N) is how hard a car nobody drives holds its place below
    0.5 m/s.
    """
    engine_force: float = 6000.0
    brake_force: float = 14000.0
    reverse_fraction: float = 0.4
    maximum_steer: float = 0.55
    steer_speed: float = 4.0
    rolling_resistance: float = 0.015
    downforce: float = 0.0
    base_speed: float = 0.0
    drag: float = 0.0
    steer_falloff_speed: float = 30.0
    holding: float = 6000.0

    def drive_force(self, speed: float) -> float:
        """What the drivetrain pushes with at ``speed`` m/s, in newtons."""
        travelling = abs(float(speed))
        if self.base_speed <= 0.0 or travelling <= self.base_speed:
            return float(self.engine_force)
        return float(self.engine_force) * float(self.base_speed) / travelling

    def steer_lock(self, speed: float) -> float:
        """How far the front wheels may turn at ``speed`` m/s, in radians.

        The lock falls with the square of the speed against
        :attr:`steer_falloff_speed`, so the sideways pull full lock asks for
        levels off as the speed rises.
        """
        falloff = float(self.steer_falloff_speed)
        if falloff <= 0.0:
            return float(self.maximum_steer)
        share = abs(float(speed)) / falloff
        return float(self.maximum_steer) / (1.0 + share * share)

    def drag_force(self, speed: float) -> float:
        """What the air pushes back with at ``speed`` m/s, in newtons."""
        return float(self.drag) * float(speed) * float(speed)


def car_wheels(wheelbase: float = 2.6, track: float = 1.6, height: float = -0.1,
               drive: str = 'rear', **wheel: Any) -> list[CarWheel]:
    """The four wheels of a car: front pair steered, ``drive`` ``'rear'``, ``'front'`` or ``'all'``.

    ``wheelbase`` is front axle to rear axle and ``track`` left wheel to
    right, in metres; ``height`` is where the suspension is mounted against
    the chassis's origin. Anything in ``wheel`` goes to every
    :class:`CarWheel`.
    """
    if drive not in ('rear', 'front', 'all'):
        raise ValueError("drive must be 'rear', 'front' or 'all', not %r" % (drive,))
    half_base, half_track = wheelbase / 2.0, track / 2.0
    return [CarWheel(position=(side * half_track, height, -half_base if front else half_base),
                     steering=front, driven=drive == 'all' or (drive == 'front') == front,
                     **wheel)
            for front in (True, False) for side in (-1.0, 1.0)]


@dataclasses.dataclass(frozen=True)
class Surface:
    """What a wheel is on: ``grip`` multiplies the tyre's friction, ``rolling`` adds to its rolling resistance.

    ``rolling`` is a fraction of the load the wheel carries.
    """
    grip: float = 1.0
    rolling: float = 0.0


#: Firm, dry ground: what a wheel is on unless something says otherwise.
TARMAC = Surface()


# -- reading ----------------------------------------------------------------

class Impact(NamedTuple):
    """The heaviest blow the chassis took in a tick: the body struck, the closing speed (m/s), the impulse (N s).

    ``body`` is None for something the service holds no handle for.
    """
    body: Body | None
    closing: float
    impulse: float


@dataclasses.dataclass(frozen=True)
class WheelState:
    """One wheel as the newest tick left it.

    ``position`` is the wheel's centre in the world and ``orientation`` an
    ``(x, y, z, w)`` quaternion turning a wheel model (axle along X, up along
    Y) to the world, steer and roll included. ``length`` is the suspension's
    length and ``compression`` how far it is compressed from full droop, in
    metres. ``steer`` and ``angle`` (rad) are the steer and the roll, ``spin``
    the roll rate (rad/s). ``load`` (N) is what the suspension carries.
    ``slip_ratio`` is the tyre's longitudinal slip, ``slip_angle`` (rad) its
    lateral slip, and ``slip`` the sideways speed across the contact (m/s).
    ``grounded`` says whether it touches the ground; ``ground`` is the body
    under it, ``material`` that body's material name (None for the default),
    ``grip`` the surface's grip, and ``contact`` and ``normal`` where and
    which way it touches.
    """
    position: np.ndarray
    orientation: np.ndarray
    length: float
    compression: float
    steer: float
    angle: float
    spin: float
    load: float
    slip_ratio: float
    slip_angle: float
    slip: float
    grounded: bool
    ground: Body | None
    material: str | None
    grip: float
    contact: np.ndarray
    normal: np.ndarray


@dataclasses.dataclass(frozen=True)
class VehicleState:
    """A vehicle as the newest tick left it.

    ``speed`` is the chassis's speed and ``forward_speed`` its speed along
    its nose (negative reversing), in m/s; ``rpm`` the motor's speed; ``gear``
    -1 for reverse, 0 neutral, 1 and up forward; ``steer_angle`` the steered
    wheels' angle (rad, positive left). ``throttle``, ``steer``, ``brake`` and
    ``handbrake`` are the inputs the tick applied. ``impact`` is the tick's
    heaviest blow; ``step`` the tick.
    """
    speed: float
    forward_speed: float
    rpm: float
    gear: int
    steer_angle: float
    throttle: float
    steer: float
    brake: float
    handbrake: float
    wheels: tuple[WheelState, ...]
    impact: Impact | None
    step: int


# -- the handle ---------------------------------------------------------------

class Vehicle:
    """The handle of one vehicle in a physics service.

    :meth:`set_input` gives the driver's inputs, held until changed; the
    reads (:meth:`state`, :attr:`forward_speed`, :attr:`wheels`,
    :meth:`impact`) are the newest tick's. The chassis is :attr:`chassis`,
    an ordinary :class:`~OpenGLContext.physics.body.Body`: its pose,
    velocity and handlers are the vehicle's.

    Inputs given during a frame reach the world in one batch with every
    other vehicle's and apply from the frame's first tick. Inputs given from
    a ``'before-step'`` handler apply at that tick.
    """

    def __init__(self, physics: Physics, uid: int, chassis: Body, settings: VehicleSettings) -> None:
        self.physics = physics
        #: The vehicle's id in its service.
        self.uid = uid
        #: The chassis's body.
        self.chassis = chassis
        #: What the vehicle was made with.
        self.settings = settings
        #: Whether the vehicle is still in the world.
        self.alive = True
        self.throttle = 0.0
        self.steer = 0.0
        self.brake = 0.0
        self.handbrake = 0.0
        #: The surface last sent for all wheels (key None) and for each wheel since.
        self._surfaces: dict[int | None, Any] = {}

    def __repr__(self) -> str:
        return '<Vehicle %d chassis=%d%s>' % (self.uid, self.chassis.uid,
                                              '' if self.alive else ' removed')

    # -- the driver -------------------------------------------------------
    def set_input(self, throttle: float = 0.0, steer: float = 0.0, brake: float = 0.0,
                  handbrake: float = 0.0) -> None:
        """The driver's inputs, held until the next call; returns None.

        ``throttle`` -1 to 1 (below 0 the gearbox selects reverse), ``steer``
        -1 to 1 (positive turns left, a positive yaw about +Y), ``brake`` and
        ``handbrake`` 0 to 1. Values outside are clamped; a non-finite one is
        a ValueError.
        """
        values = (_clamped(throttle, 'throttle', -1.0), _clamped(steer, 'steer', -1.0),
                  _clamped(brake, 'brake', 0.0), _clamped(handbrake, 'handbrake', 0.0))
        self.throttle, self.steer, self.brake, self.handbrake = values
        if self.alive:
            self.physics._engine.vehicle_input(self.uid, values)

    def set_surface(self, surface: Surface | None, wheel: int | None = None) -> None:
        """The ground under one wheel (``wheel`` its index) or under all of them; returns None.

        None gives the wheels back to the world's surfaces by material. A
        surface the same as the last one given is not sent again, so a game
        may set it every tick.
        """
        if wheel is not None and not 0 <= int(wheel) < len(self.settings.wheels):
            raise IndexError('wheel %r: this vehicle has %d' % (wheel, len(self.settings.wheels)))
        key = None if wheel is None else int(wheel)
        if key is None:
            if self._surfaces == {None: surface}:
                return
            self._surfaces = {None: surface}
        else:
            if self._surfaces.get(key, self._surfaces.get(None, _UNSENT)) == surface:
                return
            self._surfaces[key] = surface
        if self.alive:
            self.physics._engine.vehicle_surface(self.uid, key, surface)

    def place(self, position: Any, heading: float = 0.0) -> None:
        """Put the vehicle at ``position``, level, turned ``heading`` radians about +Y, and still.

        Its velocities are zeroed and its inputs sent again, so a vehicle held
        on its idle brake is driven from the new place by what it is given.
        """
        at = vector(position, 'position')
        self.chassis.set_transform(at, (0.0, 1.0, 0.0, number(heading, 'heading')))
        self.chassis.set_velocity((0.0, 0.0, 0.0))
        self.chassis.set_angular_velocity((0.0, 0.0, 0.0))
        self.set_input(self.throttle, self.steer, self.brake, self.handbrake)

    # -- reading ----------------------------------------------------------
    def state(self) -> VehicleState:
        """The vehicle as the newest tick left it; a ValueError before the world has stepped it."""
        found = self.physics._engine.vehicle_state(self.uid) if self.alive else None
        if found is None:
            raise ValueError('%r has no state: the world has not stepped it' % (self,))
        return found

    @property
    def forward_speed(self) -> float:
        """Speed along the chassis's nose, m/s; negative reversing; 0 before the first tick."""
        found = self._state_or_none()
        return 0.0 if found is None else found.forward_speed

    @property
    def speed(self) -> float:
        """The chassis's speed, m/s; 0 before the first tick."""
        found = self._state_or_none()
        return 0.0 if found is None else found.speed

    @property
    def rpm(self) -> float:
        """The motor's speed, revolutions a minute; 0 before the first tick."""
        found = self._state_or_none()
        return 0.0 if found is None else found.rpm

    @property
    def gear(self) -> int:
        """-1 reverse, 0 neutral, 1 and up forward; 0 before the first tick."""
        found = self._state_or_none()
        return 0 if found is None else found.gear

    @property
    def steer_angle(self) -> float:
        """The steered wheels' angle, rad, positive left; 0 before the first tick."""
        found = self._state_or_none()
        return 0.0 if found is None else found.steer_angle

    @property
    def wheels(self) -> tuple[WheelState, ...]:
        """Each wheel as the newest tick left it; empty before the first tick."""
        found = self._state_or_none()
        return () if found is None else found.wheels

    @property
    def grounded(self) -> bool:
        """Whether any wheel touches the ground."""
        return any(wheel.grounded for wheel in self.wheels)

    def impact(self, among: Iterable[Body] | None = None, above: float = 0.0) -> Impact | None:
        """The heaviest blow the chassis took in the newest tick, or None.

        ``above`` is the closing speed (m/s) the blow must exceed. ``among``
        limits the answer to a blow against one of those bodies: the tick's
        heaviest blow is answered when it is against one of them, and None
        otherwise.
        """
        found = self._state_or_none()
        blow = None if found is None else found.impact
        if blow is None or not blow.closing > float(above):
            return None
        if among is not None and blow.body not in set(among):
            return None
        return blow

    def _state_or_none(self) -> VehicleState | None:
        if not self.alive:
            return None
        return self.physics._engine.vehicle_state(self.uid)

    # -- events and removal -----------------------------------------------
    def addEventHandler(self, event: str, function: Callable[..., Any] | None = None,
                        **filters: Any) -> Handler | None:
        """Call ``function(collision)`` for each ``'impact'`` or ``'crash'`` of this vehicle.

        The collision's ``body`` is the chassis and ``other`` the body struck;
        ``approach`` is the closing speed. ``other=`` and ``above=`` filter as
        they do for a body (:meth:`Body.addEventHandler
        <OpenGLContext.physics.body.Body.addEventHandler>`). Every event of
        a body is open to the chassis through :attr:`chassis` as well.
        """
        if event not in ('impact', 'crash'):
            raise ValueError("a vehicle's events are 'impact' and 'crash', not %r" % (event,))
        return self.chassis.addEventHandler(event, function, **filters)

    def remove(self) -> None:
        """Take the vehicle out of the world; the chassis stays a body. Removing twice is harmless."""
        if not self.alive:
            return
        self.alive = False
        self.physics._remove_vehicle(self)


#: Stands for a surface never sent, which no surface equals.
_UNSENT = object()


def _clamped(value: float, name: str, low: float) -> float:
    return min(1.0, max(low, number(value, name)))
