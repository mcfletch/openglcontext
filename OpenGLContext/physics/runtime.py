"""WorldRuntime: the worker-side state of a physics service.

One omi_physics world, the table that maps the application's body ids to the
world's slots, and everything that is done to them: applying a
:class:`~OpenGLContext.physics.records.Command`, stepping by a fixed step,
publishing a :class:`~OpenGLContext.physics.records.Snapshot` and turning the
world's contact log into :class:`~OpenGLContext.physics.records.PhysicsEvent`
records that name bodies by id.

A runtime holds no scenegraph and no GL, and it is touched by one thread at a
time: the thread that steps it. The workers in :mod:`OpenGLContext.physics.worker`
decide which that is.
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from omi_physics import mathutil, model
from omi_physics.contactevents import BodyRef, ContactEvent, TriggerEvent, Verdict
from omi_physics.joints import (
    BallJoint, DistanceConstraint, HingeJoint, MotorJoint, SliderJoint, TwoAxisHingeJoint,
    UniversalJoint,
)
from omi_physics.massprops import inertia_diagonal
from omi_physics.world import PhysicsWorld

from OpenGLContext.events.framestep import FixedSteps
from OpenGLContext.physics import omi_adapter
from OpenGLContext.physics.omi_adapter import omi_shape
from OpenGLContext.physics.joints import JointSpec
from OpenGLContext.physics.records import BodyBatch, BodySpec, Command, PhysicsEvent, Snapshot, Step
from OpenGLContext.physics.settings import PhysicsDefinition

__all__ = ['JointTable', 'WorldRuntime', 'build_joint', 'give_mass']

log = logging.getLogger(__name__)

#: How many removed bodies the runtime still names in events about their last contacts.
RETIRED_KEPT = 4096
_ZERO3 = np.zeros(3)
_STATE = ('sleep', 'wake')


def give_mass(world: PhysicsWorld, index: int, shape: model.Shape, mass: float) -> None:
    """Make the dynamic body at row ``index`` of ``world`` weigh ``mass`` kilograms.

    The inertia is the shape's for that mass, about the body's own axes.
    """
    world.mass[index] = mass
    world.inv_mass[index] = 1.0 / mass
    diagonal = inertia_diagonal(shape, mass)
    world.inv_inertia[index] = np.where(diagonal > 0.0, 1.0 / np.maximum(diagonal, 1e-12), 0.0)


_ORIGIN = (0.0, 0.0, 0.0)
_UP = (0.0, 1.0, 0.0)


def build_joint(spec: JointSpec, world: PhysicsWorld, body: int, to: int) -> Any:
    """The omi_physics constraint for ``spec`` between world slots ``body`` and ``to`` (-1, the world)."""
    anchor, axis = spec.anchor or _ORIGIN, spec.axis or _UP
    made: Any
    if spec.kind == 'hinge':
        made = HingeJoint(to, body, anchor, axis, lower=spec.lower, upper=spec.upper,
                          motor_speed=spec.speed, motor_torque=spec.force)
    elif spec.kind == 'ball':
        made = BallJoint(to, body, anchor)
    elif spec.kind == 'slider':
        made = SliderJoint(to, body, axis, lower=spec.lower, upper=spec.upper,
                           motor_speed=spec.speed, motor_force=spec.force)
    elif spec.kind == 'universal':
        made = UniversalJoint(to, body, anchor, spec.to_axis or _UP, axis)
    elif spec.kind == 'wheel':
        made = TwoAxisHingeJoint(to, body, anchor, axis, spec.to_axis or _UP, lower1=spec.lower,
                                 upper1=spec.upper, motor1_speed=spec.steer_speed,
                                 motor1_torque=spec.steer_force, motor2_speed=spec.speed,
                                 motor2_torque=spec.force, suspension_stiffness=spec.stiffness,
                                 suspension_damping=spec.damping)
    elif spec.kind == 'motor':
        made = MotorJoint(to, body, spec.axes, spec.torques)
    else:
        made = DistanceConstraint(to, body, _local(world, to, spec.to_anchor or _ORIGIN),
                                  _local(world, body, anchor), length=spec.length)
    made.collide_connected = spec.collide
    return made


def _local(world: PhysicsWorld, slot: int, point: Any) -> np.ndarray:
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

    def __contains__(self, joint: int) -> bool:
        return joint in self._held

    def add(self, world: PhysicsWorld, joint: int, spec: JointSpec, body: int | None,
            to: int | None) -> None:
        """Make joint ``joint`` from ``spec`` between world slots ``body`` and ``to`` (-1, the world).

        A slot of None is a body that has left the world, and the joint is not made.
        """
        if body is None or to is None:
            log.warning('joint %d names a body that has left the world; it is not made', joint)
            return
        made = world.add_joint_constraint(build_joint(spec, world, body, to))
        self._held[joint] = (made, spec.body, spec.to)

    def remove(self, world: PhysicsWorld, joint: int) -> None:
        """Take joint ``joint`` out of the world; one that is not there is ignored."""
        held = self._held.pop(joint, None)
        if held is not None:
            world.remove_joint_constraint(held[0])
            self._wake(world, held[0])

    @staticmethod
    def _wake(world: PhysicsWorld, made: Any) -> None:
        for slot in (getattr(made, 'a', -1), getattr(made, 'b', -1)):
            if slot >= 0:
                world.wake(slot)

    def motor(self, world: PhysicsWorld, joint: int, speed: float, force: float) -> None:
        """Give joint ``joint``'s motor (a wheel's axle motor) a new speed and limit, and wake its bodies."""
        held = self._held.get(joint)
        if held is None:
            return
        made = held[0]
        if isinstance(made, TwoAxisHingeJoint):
            made.motor2_speed, made.motor2_torque = float(speed), float(force)
        elif isinstance(made, SliderJoint):
            made.motor_speed, made.motor_force = float(speed), float(force)
        else:
            made.motor_speed, made.motor_torque = float(speed), float(force)
        self._wake(world, made)

    def torques(self, world: PhysicsWorld, joint: int, torques: tuple[float, ...]) -> None:
        """Give motor joint ``joint`` new torques about its axes, and wake its bodies."""
        held = self._held.get(joint)
        if held is not None and isinstance(held[0], MotorJoint):
            held[0].torques = [float(value) for value in torques]
            self._wake(world, held[0])

    def reading(self, world: PhysicsWorld, joint: int) -> tuple[float, ...]:
        """Joint ``joint``'s angles in radians, or a slider's slide in metres; () for none."""
        made = self._held[joint][0]
        if isinstance(made, TwoAxisHingeJoint):
            return (float(made.angle1(world)), float(made.angle2(world)))
        if isinstance(made, HingeJoint):
            return (float(made.angle(world)),)
        if isinstance(made, SliderJoint):
            return (float(made.separation(world)),)
        if isinstance(made, MotorJoint):
            return tuple(float(made.angle(world, index)) for index in range(len(made.axes_world)))
        return ()

    def forget_body(self, world: PhysicsWorld, body: int) -> None:
        """Remove the joints of body id ``body``, which is leaving the world."""
        for joint in [joint for joint, held in self._held.items() if body in held[1:]]:
            self.remove(world, joint)


class _Entry:
    """Where body ``uid`` is in the world and what kind of body it is."""

    __slots__ = ('index', 'kind', 'proxy', 'uid')

    def __init__(self, uid: int, index: int, kind: str, proxy: Any) -> None:
        self.uid = uid
        self.index = index
        self.kind = kind
        self.proxy = proxy


class WorldRuntime:
    """A world, its bodies by id, and the changes made to it."""

    def __init__(self, definition: PhysicsDefinition) -> None:
        definition.validate()
        self.step_dt = 1.0 / float(definition.tickHz)
        self.max_catch_up = float(definition.maxCatchUp)
        try:
            self.world = PhysicsWorld(gravity=omi_adapter.gravity(definition.gravity),
                                      fixed_dt=self.step_dt, backend=definition.backend)
        except Exception as error:  # noqa: BLE001 a backend that cannot be made leaves the default
            log.warning('the %s physics backend could not be made (%s); the world steps on auto',
                        definition.backend, error)
            self.world = PhysicsWorld(gravity=omi_adapter.gravity(definition.gravity),
                                      fixed_dt=self.step_dt, backend='auto')
        self.world.log_events = False
        #: Called with each :class:`Step` before and after the world steps.
        self.before_step: list[Callable[[Step], Any]] = []
        self.after_step: list[Callable[[Step], Any]] = []
        #: Called with the events a step made, right after it, on the stepping thread.
        self.on_events: list[Callable[[list[PhysicsEvent]], Any]] = []
        #: Asked by :meth:`busy`; one that answers True keeps the world stepping while nothing moves.
        self.wants_steps: list[Callable[[], bool]] = []
        #: The highest sequence number below which every command has been applied.
        self.applied_seq = 0
        #: Sequence numbers applied ahead of one still on its way.
        self._applied_ahead: set[int] = set()
        #: How many commands have been applied, in all.
        self.applied_count = 0
        self.version = 0
        #: Events a ``settle`` command left to be set once the next snapshot is published.
        self.markers: list[threading.Event] = []
        #: The whole steps each frame owes, and the part step carried to the next.
        self.clock = FixedSteps(self.step_dt, self.max_catch_up)
        self._entries: dict[int, _Entry] = {}
        self._shapes: dict[int, int] = {}
        self._materials: dict[str, int] = {}
        #: The index of each unnamed material by its values, so a body given the same
        #: coefficients again shares the one made for them.
        self._unnamed: dict[tuple[Any, ...], int] = {}
        self._retired: collections.OrderedDict[BodyRef, int] = collections.OrderedDict()
        self._events: list[PhysicsEvent] = []
        self._movers: tuple[np.ndarray, np.ndarray, dict[int, int]] | None = None
        #: The last snapshot made, and which of its rows moved, that the next lists its changes from.
        self._published: Snapshot | None = None
        self._published_live = np.zeros(0, dtype=bool)
        self._asleep: dict[int, bool] = {}
        self._watch_state = False
        #: Stand-ins of characters, by id, with the heaviest body each pushes; see ``_filter``.
        self.standins: dict[int, float] = {}
        #: Functions that give a kinematic body its pose at a time, by body id.
        self.drivers: dict[int, Callable[[float], Any]] = {}
        #: The joints in the world, by joint id.
        self.joints = JointTable()
        #: The joints whose readings each snapshot carries.
        self.watched_joints: set[int] = set()
        #: The application's contact filter, asked after the stand-ins' rule; None for none.
        self.contact_filter: Callable[[Any], Any] | None = None
        self._thread = threading.get_ident()
        self.world.set_contact_filter(self._filter)

    # -- bodies ---------------------------------------------------------
    def entry(self, uid: int) -> _Entry:
        """The entry of body ``uid``; KeyError if it is not in the world."""
        return self._entries[uid]

    def __contains__(self, uid: int) -> bool:
        return uid in self._entries

    def bind_thread(self) -> None:
        """Make the calling thread the one that steps this runtime."""
        self._thread = threading.get_ident()

    def on_stepping_thread(self) -> bool:
        """Whether the calling thread is the one that steps this runtime."""
        return threading.get_ident() == self._thread

    # -- commands -------------------------------------------------------
    def apply(self, command: Command) -> None:
        """Make one change. A command for a body that has left the world is dropped.

        :attr:`applied_seq` reaches a command's sequence number once every
        command numbered before it has been applied too: a physics callback's
        write is applied in the step while a write the render thread made
        before it can still be waiting in the inbox.
        """
        self.applied_count += 1
        if command.seq > self.applied_seq:
            self._count_applied(command.seq)
        operation = getattr(self, '_op_' + command.op, None)
        if operation is None:
            log.warning('unknown physics command %r', command.op)
            return
        if command.uid and command.op != 'add' and command.uid not in self._entries:
            return
        try:
            operation(command.uid, *command.args)
        except Exception:
            log.exception('physics command %s for body %s failed', command.op, command.uid)

    def _count_applied(self, seq: int) -> None:
        ahead = self._applied_ahead
        ahead.add(seq)
        while self.applied_seq + 1 in ahead:
            self.applied_seq += 1
            ahead.discard(self.applied_seq)

    def _op_add(self, uid: int, spec: BodySpec) -> None:
        world = self.world
        proxy = spec.proxy
        index_of_shape = self._shapes.get(proxy.uid)
        if index_of_shape is None:
            index_of_shape = self._shapes[proxy.uid] = world.add_shape(omi_shape(proxy))
        given = spec.motion
        motion = omi_adapter.motion(spec.kind, given.mass, given.linear_damping,
                                    given.angular_damping, given.gravity_factor)
        collider = trigger = None
        if spec.kind == 'trigger':
            trigger = model.Trigger(shape=index_of_shape, collisionFilter=spec.collision_filter)
        else:
            collider = model.Collider(shape=index_of_shape,
                                      physicsMaterial=self.material_index(spec.material),
                                      collisionFilter=spec.collision_filter)
        report = spec.report or spec.kind == 'trigger'
        index = world.add_body(motion, collider, trigger, position=spec.position,
                               orientation=spec.orientation, handle=spec.uid,
                               report_contacts=report, sensor=spec.sensor)
        if report and world.contact_reporting == 'off':
            world.contact_reporting = 'flagged'
        self._entries[spec.uid] = _Entry(spec.uid, index, spec.kind, proxy)
        self._movers = None

    def _op_add_many(self, uid: int, batch: BodyBatch) -> None:  # noqa: ARG002 named by the batch
        world = self.world
        shape = self._shapes.get(batch.proxy.uid)
        if shape is None:
            shape = self._shapes[batch.proxy.uid] = world.add_shape(omi_shape(batch.proxy))
        collider = model.Collider(shape=shape, physicsMaterial=self.material_index(batch.material),
                                  collisionFilter=batch.collision_filter)
        indices = world.add_bodies(shape, batch.positions, collider=collider)
        for offset, index in enumerate(indices.tolist()):
            self._entries[batch.first + offset] = _Entry(batch.first + offset, int(index),
                                                         'static', batch.proxy)

    def _op_remove_many(self, uid: int, first: int, count: int) -> None:  # noqa: ARG002 named by the range
        for number in range(first, first + count):
            if number in self._entries:
                self._op_remove(number)

    def _op_remove(self, uid: int) -> None:
        self.drivers.pop(uid, None)
        if len(self.joints):
            self.joints.forget_body(self.world, uid)
        entry = self._entries.pop(uid)
        world = self.world
        ref = world.ref(entry.index)
        self._retired[ref] = uid
        while len(self._retired) > RETIRED_KEPT:
            self._retired.popitem(last=False)
        world.remove_body(entry.index)
        self._events.extend(self._collect_events())
        self._asleep.pop(uid, None)
        self._movers = None

    def _op_impulse(self, uid: int, impulse: Any, at: Any) -> None:
        world = self.world
        index = self._entries[uid].index
        push = np.asarray(impulse, dtype='d')
        world.apply_impulse(index, push)
        if at is not None:
            arm = np.asarray(at, dtype='d') - world.position[index]
            world.apply_angular_impulse(index, np.cross(arm, push))

    def _op_torque_impulse(self, uid: int, impulse: Any) -> None:
        self.world.apply_angular_impulse(self._entries[uid].index, np.asarray(impulse, dtype='d'))

    def _op_force(self, uid: int, force: Any) -> None:
        self.world.set_force(self._entries[uid].index, force)

    def _op_torque(self, uid: int, torque: Any) -> None:
        self.world.set_torque(self._entries[uid].index, torque)

    def _op_velocity(self, uid: int, velocity: Any) -> None:
        index = self._entries[uid].index
        self.world.linear_velocity[index] = np.asarray(velocity, dtype='d')
        self.world.wake(index)

    def _op_angular_velocity(self, uid: int, velocity: Any) -> None:
        index = self._entries[uid].index
        self.world.angular_velocity[index] = np.asarray(velocity, dtype='d')
        self.world.wake(index)

    def _op_place(self, uid: int, translation: Any, axis_angle: Any) -> None:
        index = self._entries[uid].index
        orientation = None
        if axis_angle is not None:
            x, y, z, angle = (float(v) for v in axis_angle)
            orientation = mathutil.quat_from_axis_angle((x, y, z), angle)
        self.world.place_body(index, translation, orientation)
        self.world.wake(index)

    def _op_gravity(self, uid: int, vector: Any) -> None:  # noqa: ARG002 gravity belongs to the world
        self.world.gravity = omi_adapter.gravity(vector)

    def _op_gravity_factor(self, uid: int, factor: float) -> None:
        index = self._entries[uid].index
        self.world.gravity_factor[index] = float(factor)
        self.world.wake(index)

    def _op_damping(self, uid: int, linear: float | None, angular: float | None) -> None:
        index = self._entries[uid].index
        if linear is not None:
            self.world.linear_damping[index] = float(linear)
        if angular is not None:
            self.world.angular_damping[index] = float(angular)

    def _op_config(self, uid: int, tick_hz: float, max_catch_up: float) -> None:  # noqa: ARG002 world-wide
        self.step_dt = 1.0 / float(tick_hz)
        self.max_catch_up = float(max_catch_up)
        self.clock.step, self.clock.longest = self.step_dt, self.max_catch_up
        self.world.fixed_dt = self.step_dt

    def _op_drop_remainder(self, uid: int) -> None:  # noqa: ARG002 world-wide
        self.clock.drop()

    def _op_logging(self, uid: int, on: bool) -> None:  # noqa: ARG002 world-wide
        self.set_logging(on)

    def _op_run(self, uid: int, function: Callable[[Any], Any],  # noqa: ARG002 world-wide
                future: Any) -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(function(self.world))
        except BaseException as error:
            future.set_exception(error)

    def _op_post(self, uid: int, function: Callable[..., Any],  # noqa: ARG002 world-wide
                 arguments: tuple[Any, ...]) -> None:
        function(*arguments)

    def _op_backend(self, uid: int, name: str) -> None:  # noqa: ARG002 the backend is the world's
        try:
            self.world.use_backend(name)
        except Exception as error:  # noqa: BLE001 any failure to build one leaves the world as it was
            log.warning('the %s physics backend could not be made (%s); the world keeps %s',
                        name, error, self.world.backend.name)

    def _op_joint(self, uid: int, joint: int, spec: JointSpec) -> None:
        to = -1 if spec.to == 0 else getattr(self._entries.get(spec.to), 'index', None)
        self.joints.add(self.world, joint, spec, self._entries[uid].index, to)

    def _op_unjoint(self, uid: int, joint: int) -> None:  # noqa: ARG002 named by the joint
        self.joints.remove(self.world, joint)
        self.watched_joints.discard(joint)

    def _op_joint_watch(self, uid: int, joint: int) -> None:  # noqa: ARG002 named by the joint
        self.watched_joints.add(joint)

    def _op_joint_torques(self, uid: int, joint: int,  # noqa: ARG002 named by the joint
                          torques: tuple[float, ...]) -> None:
        self.joints.torques(self.world, joint, torques)

    def _op_joint_motor(self, uid: int, joint: int, speed: float,  # noqa: ARG002 named by the joint
                        force: float) -> None:
        self.joints.motor(self.world, joint, speed, force)

    def _op_standin(self, uid: int, body: int, push_mass: float) -> None:  # noqa: ARG002 world-wide
        self.standins[body] = float(push_mass)

    def _filter(self, pair: Any) -> Any:
        """Let a character's stand-in pass through a body heavier than the character can push.

        The stand-in is infinitely heavy to the solver; without this it would
        shove a truck. The character is blocked by such a body in its own step.
        Any other pair is the application's :attr:`contact_filter` to judge.
        """
        if not self.standins:
            return Verdict.SOLVE if self.contact_filter is None else self.contact_filter(pair)
        world = self.world
        first, second = world.handle_of(pair.a), world.handle_of(pair.b)
        for mine, other in ((first, second), (second, first)):
            limit = self.standins.get(mine) if mine is not None else None
            if limit is None or other is None or other not in self._entries:
                continue
            index = self._entries[other].index
            if world.motion_type[index] == 2 and float(world.mass[index]) > limit:
                return Verdict.IGNORE_PAIR
        return Verdict.SOLVE if self.contact_filter is None else self.contact_filter(pair)

    def _op_contact_filter(self, uid: int,  # noqa: ARG002 the filter is the world's
                           function: Callable[[Any], Any] | None) -> None:
        self.contact_filter = function

    def _op_filter(self, uid: int, index: int,  # noqa: ARG002 filters are the world's
                   given: Any) -> None:
        collision_filter = omi_adapter.omi_filter(given)
        filters = self.world.filters
        while len(filters) < index:
            filters.append(model.CollisionFilter())
        if index < len(filters):
            filters[index] = collision_filter
        else:
            filters.append(collision_filter)

    def _op_noop(self, uid: int) -> None:
        """Do nothing; a command whose arrival wakes a blocked worker."""

    def _op_settle(self, uid: int, marker: threading.Event) -> None:
        self.markers.append(marker)

    def _op_drive(self, uid: int, function: Callable[[float], Any] | None) -> None:
        if function is None:
            self.drivers.pop(uid, None)
        else:
            self.drivers[uid] = function

    def _drive(self, step: Step) -> None:
        """Give each driven kinematic body the velocity that takes it to its pose at the step's end."""
        world = self.world
        until = step.time + step.dt
        for uid, function in list(self.drivers.items()):
            entry = self._entries.get(uid)
            if entry is None:
                continue
            try:
                translation, rotation = function(until)
            except Exception:
                log.exception('the pose function of body %d failed', uid)
                continue
            index = entry.index
            world.linear_velocity[index] = (np.asarray(translation, dtype='d')
                                            - world.position[index]) / step.dt
            if rotation is not None:
                x, y, z, angle = (float(v) for v in rotation)
                target = mathutil.quat_from_axis_angle((x, y, z), angle)
                world.angular_velocity[index] = _turn_between(
                    world.orientation[index], target) / step.dt
            world.wake(index)

    def _op_material(self, uid: int, name: str, material: Any) -> None:  # noqa: ARG002 world-wide
        self.define_material(name, material)

    def _op_pair_friction(self, uid: int, first: str, second: str,  # noqa: ARG002 world-wide
                          static: float, dynamic: float) -> None:
        self.world.set_pair_friction(self.material_index(first), self.material_index(second),
                                     static, dynamic)

    def _op_gravity_zone(self, uid: int, zone: Any) -> None:  # noqa: ARG002 world-wide
        self.world.add_gravity_volume(omi_adapter.gravity_volume(zone))

    def _op_gravity_zones(self, uid: int, kind: type, zones: list[Any]) -> None:  # noqa: ARG002 world-wide
        """Replace the world's volumes whose region is of ``kind`` with volumes of ``zones``."""
        kept = [volume for volume in self.world.gravity_volumes
                if not isinstance(getattr(volume, 'region', None), kind)]
        self.world.gravity_volumes[:] = kept + [omi_adapter.gravity_volume(zone) for zone in zones]

    def _op_mass(self, uid: int, mass: float) -> None:
        entry = self._entries[uid]
        give_mass(self.world, entry.index, omi_shape(entry.proxy), mass)
        self.world.wake(entry.index)

    def _op_body_material(self, uid: int, material: Any) -> None:
        entry = self._entries[uid]
        self.world.collider_material[entry.index] = self.material_index(material)
        self.world.wake(entry.index)

    def _op_wake(self, uid: int) -> None:
        self.world.wake(self._entries[uid].index)

    def _op_report(self, uid: int, on: bool) -> None:
        world = self.world
        world.report_contacts(self._entries[uid].index, bool(on))
        if on and world.contact_reporting == 'off':
            world.contact_reporting = 'flagged'

    def _op_report_all(self, uid: int, on: bool) -> None:  # noqa: ARG002 reporting everything is the world's
        self.world.contact_reporting = 'all' if on else 'off'

    def _op_persist(self, uid: int, on: bool) -> None:  # noqa: ARG002 persist is the world's
        self.world.report_persist = bool(on)

    def _op_state_events(self, uid: int, on: bool) -> None:  # noqa: ARG002 state events are the world's
        self._watch_state = bool(on)

    def set_logging(self, on: bool) -> None:
        """Have the world record contacts and triggers so :meth:`take_events` finds them.

        Nothing is recorded until a body is flagged for reporting or the world
        reports every pair; triggers are always reported once this is on.
        """
        self.world.log_events = bool(on)

    # -- materials ------------------------------------------------------
    def material_index(self, material: Any) -> int:
        """The world's index for a preset or defined name, a Material (the service's or omi's), or an index; -1 for none."""
        if material is None:
            return -1
        if isinstance(material, (int, np.integer)):
            return int(material)
        if isinstance(material, str):
            found = self._materials.get(material)
            if found is None:
                if material not in model.MATERIAL_PRESETS:
                    raise ValueError('no material is defined or preset as %r' % (material,))
                found = self._materials[material] = self.world.add_material(
                    model.MATERIAL_PRESETS[material])
            return found
        made = omi_adapter.omi_material(material)
        values = dataclasses.astuple(made)
        found = self._unnamed.get(values)
        if found is None:
            found = self._unnamed[values] = int(self.world.add_material(made))
        return found

    def define_material(self, name: str, material: Any) -> int:
        """Make ``material`` the one called ``name``; the index it has in the world."""
        index = self._materials[name] = self.world.add_material(omi_adapter.omi_material(material))
        return index

    # -- stepping -------------------------------------------------------
    def step_frame(self, dt: float) -> int:
        """Add ``dt`` seconds, capped at the catch-up, and run the whole steps that fit.

        Returns how many steps ran. What is left of a step carries to the next call.
        """
        steps = self.clock.owed(dt)
        for _ in range(steps):
            self.step_once()
        return steps

    @property
    def alpha(self) -> float:
        """How far through the next step the time left over from the last frame is, 0 to 1."""
        return self.clock.alpha

    def step_once(self) -> None:
        """Run one fixed step, with its hooks, and collect the events it made."""
        world = self.world
        step = Step(self.step_dt, world.step_count, world.time)
        if self.drivers:
            self._drive(step)
        self._run_hooks(self.before_step, step)
        world.step(self.step_dt)
        made = self._collect_events()
        if self._watch_state:
            made.extend(self._state_events(step))
        self._run_hooks(self.after_step, step)
        if made:
            self._events.extend(made)
            for listener in self.on_events:
                self._run_hooks([listener], made)

    @staticmethod
    def _run_hooks(hooks: list[Callable[[Any], Any]], argument: Any) -> None:
        for hook in list(hooks):
            try:
                hook(argument)
            except Exception:
                log.exception('physics hook %r failed', hook)

    def busy(self) -> bool:
        """Whether the world needs its next step.

        It does while a dynamic body is awake, a kinematic one moves, a body has
        a driver, or one of :attr:`wants_steps` answers True. A world that is not
        busy is not stepped, so its clock stands until a command arrives.
        """
        if self.drivers or any(wants() for wants in self.wants_steps):
            return True
        _uids, indices, _rows = self._mover_table()
        if len(indices) == 0:
            return False
        world = self.world
        kind = world.motion_type[indices]
        if bool(np.any(world.awake[indices] & (kind == 2))):
            return True
        moving = np.abs(world.linear_velocity[indices]).sum(axis=1) + np.abs(
            world.angular_velocity[indices]).sum(axis=1)
        return bool(np.any((kind == 1) & (moving > 0.0)))

    # -- publishing -----------------------------------------------------
    def _mover_table(self) -> tuple[np.ndarray, np.ndarray, dict[int, int]]:
        if self._movers is None:
            movers = [(entry.uid, entry.index) for entry in self._entries.values()
                      if entry.kind not in ('static', 'trigger')]
            uids = np.array([uid for uid, _ in movers], dtype='i8')
            indices = np.array([index for _, index in movers], dtype='i8')
            self._movers = (uids, indices, {int(uid): row for row, uid in enumerate(uids)})
        return self._movers

    def snapshot(self, alpha: float = 1.0) -> Snapshot:
        """The poses and velocities of the bodies that move, ``alpha`` of the way through a step.

        Only the rows that can differ from the last snapshot are worked out
        again: the bodies that move now or moved then, and any other whose
        pose, velocity or sleep the world holds differently from what that
        snapshot published (a body moved by hand). The rest are copied.
        """
        uids, indices, rows = self._mover_table()
        world = self.world
        self.version += 1
        last = self._published
        awake = world.awake[indices]
        dynamic = world.motion_type[indices] == 2
        linear = world.linear_velocity[indices]
        angular = world.angular_velocity[indices]
        live = np.where(dynamic, awake, linear.any(axis=1) | angular.any(axis=1))
        exact_position = world.position[indices]
        exact_orientation = world.orientation[indices]
        if last is None or last.rows is not rows:
            position, orientation = exact_position, exact_orientation
            axis_angle = np.zeros((len(indices), 4))
            changed = None
            redo = np.flatnonzero(np.ones(len(indices), dtype=bool))
        else:
            differs = live | self._published_live
            still = np.flatnonzero(~differs)
            if len(still):
                differs[still] = ((exact_position[still] != last.position[still]).any(axis=1)
                                  | (exact_orientation[still] != last.orientation[still]).any(axis=1)
                                  | (linear[still] != last.linear_velocity[still]).any(axis=1)
                                  | (angular[still] != last.angular_velocity[still]).any(axis=1)
                                  | (awake[still] != last.awake[still]))
            redo = changed = np.flatnonzero(differs)
            if not len(redo):
                snapshot = Snapshot(self.version, world.step_count, world.time, self.applied_seq,
                                    rows, last.position, last.axis_angle, last.orientation,
                                    last.linear_velocity, last.angular_velocity, last.awake,
                                    last.dynamic, changed, last.version, last.step_position,
                                    last.step_orientation, self._joint_readings(),
                                    world.live_body_count, len(world.contacts))
                self._published = snapshot
                return snapshot
            if len(redo) == len(indices):
                # Every row is worked out again, so none is copied from the last.
                position, orientation = exact_position, exact_orientation
                axis_angle = np.zeros((len(indices), 4))
            else:
                position, orientation = last.position.copy(), last.orientation.copy()
                axis_angle = last.axis_angle.copy()
                position[redo] = exact_position[redo]
                orientation[redo] = exact_orientation[redo]
        moving = redo[live[redo]]
        step_position = step_orientation = None
        if len(moving) and alpha < 1.0:
            if position is exact_position:
                position, orientation = position.copy(), orientation.copy()
            step_position, step_orientation = exact_position, exact_orientation
            take = indices[moving]
            position[moving] = (world.prev_position[take] * (1.0 - alpha)
                                + world.position[take] * alpha)
            orientation[moving] = mathutil.quat_normalize(
                world.prev_orientation[take] * (1.0 - alpha) + world.orientation[take] * alpha)
        if len(redo):
            axis_angle[redo] = mathutil.quat_to_axis_angle(orientation[redo])
        snapshot = Snapshot(self.version, world.step_count, world.time, self.applied_seq, rows,
                            position, axis_angle, orientation, linear, angular, awake, dynamic,
                            changed, -1 if last is None else last.version, step_position,
                            step_orientation, self._joint_readings(),
                            world.live_body_count, len(world.contacts))
        self._published = snapshot
        self._published_live = live
        return snapshot

    def _joint_readings(self) -> dict[int, tuple[float, ...]]:
        """The readings of the joints whose readings have been asked for, by joint id."""
        if not self.watched_joints:
            return {}
        return {joint: self.joints.reading(self.world, joint) for joint in self.watched_joints
                if joint in self.joints}

    # -- events ---------------------------------------------------------
    def take_events(self) -> list[PhysicsEvent]:
        """The events made since the last call, oldest first."""
        events, self._events = self._events, []
        return events

    def _uid_of(self, ref: BodyRef) -> int | None:
        found = self.world.handle_of(ref)
        if found is None:
            return self._retired.get(ref)
        return int(found)

    def _collect_events(self) -> list[PhysicsEvent]:
        drained = self.world.contact_log.drain()
        made: list[PhysicsEvent] = []
        for event in drained:
            converted = self._convert(event)
            if converted is not None:
                made.append(converted)
        return made

    def _convert(self, event: Any) -> PhysicsEvent | None:
        if isinstance(event, ContactEvent):
            a, b = self._uid_of(event.a), self._uid_of(event.b)
            if a is None or b is None:
                return None
            return PhysicsEvent('contact', event.phase, a, b, event.point, event.normal,
                                event.approach, event.impulse, event.friction_impulse,
                                event.slip, event.depth, event.step, event.time,
                                event.solved, event.reason)
        if isinstance(event, TriggerEvent):
            trigger, other = self._uid_of(event.trigger), self._uid_of(event.other)
            if trigger is None or other is None:
                return None
            return PhysicsEvent('trigger', event.phase, trigger, other, event.point, _ZERO3,
                                0.0, 0.0, 0.0, 0.0, 0.0, event.step, event.time)
        return None

    def _state_events(self, step: Step) -> list[PhysicsEvent]:
        """A ``'sleep'`` or ``'wake'`` event for each body whose sleep changed this step."""
        uids, indices, _rows = self._mover_table()
        made = []
        awake = self.world.awake
        for uid, index in zip(uids.tolist(), indices.tolist(), strict=True):
            asleep = not bool(awake[index])
            if self._asleep.get(uid, False) != asleep:
                self._asleep[uid] = asleep
                made.append(PhysicsEvent(
                    'state', 'sleep' if asleep else 'wake', uid, None,
                    self.world.position[index].copy(), _ZERO3, 0.0, 0.0, 0.0, 0.0, 0.0,
                    step.index, self.world.time))
        return made


def _turn_between(current: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The spin, about the world axes, that turns the quaternion ``current`` into ``target``, in radians."""
    x1, y1, z1, w1 = (float(v) for v in current)
    x2, y2, z2, w2 = (float(v) for v in target)
    # target * conjugate(current)
    x = w2 * -x1 + x2 * w1 + y2 * -z1 - z2 * -y1
    y = w2 * -y1 - x2 * -z1 + y2 * w1 + z2 * -x1
    z = w2 * -z1 + x2 * -y1 - y2 * -x1 + z2 * w1
    w = w2 * w1 - x2 * -x1 - y2 * -y1 - z2 * -z1
    if w < 0.0:
        x, y, z, w = -x, -y, -z, -w
    sine = (x * x + y * y + z * z) ** 0.5
    if sine < 1e-12:
        return np.zeros(3)
    angle = 2.0 * np.arctan2(sine, w)
    return np.array([x, y, z]) / sine * angle
