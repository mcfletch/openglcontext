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
import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from omi_physics import mathutil, model
from omi_physics.contactevents import BodyRef, ContactEvent, TriggerEvent
from omi_physics.world import PhysicsWorld

from OpenGLContext.physics.records import BodySpec, Command, PhysicsEvent, Snapshot, Step
from OpenGLContext.physics.settings import PhysicsDefinition

__all__ = ['WorldRuntime']

log = logging.getLogger(__name__)

#: How many removed bodies the runtime still names in events about their last contacts.
RETIRED_KEPT = 4096
#: A fraction of a step that floating-point error may leave short of a whole one.
_HAIR = 1e-9
_ZERO3 = np.zeros(3)
_STATE = ('sleep', 'wake')


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
        self.world = PhysicsWorld(
            gravity=definition.world_gravity(), fixed_dt=self.step_dt)
        self.world.log_events = False
        #: Called with each :class:`Step` before and after the world steps.
        self.before_step: list[Callable[[Step], Any]] = []
        self.after_step: list[Callable[[Step], Any]] = []
        #: Called with the events a step made, right after it, on the stepping thread.
        self.on_events: list[Callable[[list[PhysicsEvent]], Any]] = []
        self.applied_seq = 0
        self.version = 0
        #: Events a ``settle`` command left to be set once the next snapshot is published.
        self.markers: list[threading.Event] = []
        self._accumulator = 0.0
        self._entries: dict[int, _Entry] = {}
        self._shapes: dict[int, int] = {}
        self._materials: dict[str, int] = {}
        self._retired: collections.OrderedDict[BodyRef, int] = collections.OrderedDict()
        self._events: list[PhysicsEvent] = []
        self._movers: tuple[np.ndarray, np.ndarray, dict[int, int]] | None = None
        self._asleep: dict[int, bool] = {}
        self._watch_state = False
        self._thread = threading.get_ident()

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
        """Make one change. A command for a body that has left the world is dropped."""
        if command.seq > self.applied_seq:
            self.applied_seq = command.seq
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

    def _op_add(self, uid: int, spec: BodySpec) -> None:
        world = self.world
        proxy = spec.proxy
        index_of_shape = self._shapes.get(proxy.uid)
        if index_of_shape is None:
            index_of_shape = self._shapes[proxy.uid] = world.add_shape(proxy.shape)
        motion = spec.motion
        if spec.kind in ('static', 'trigger'):
            motion = model.Motion(type=model.STATIC)
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

    def _op_remove(self, uid: int) -> None:
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
        x, y, z = (float(v) for v in vector)
        strength = (x * x + y * y + z * z) ** 0.5
        if strength == 0.0:
            self.world.gravity = model.Gravity(gravity=0.0, direction=(0.0, -1.0, 0.0))
        else:
            self.world.gravity = model.Gravity(
                gravity=strength, direction=(x / strength, y / strength, z / strength))

    def _op_damping(self, uid: int, linear: float | None, angular: float | None) -> None:
        index = self._entries[uid].index
        if linear is not None:
            self.world.linear_damping[index] = float(linear)
        if angular is not None:
            self.world.angular_damping[index] = float(angular)

    def _op_config(self, uid: int, tick_hz: float, max_catch_up: float) -> None:  # noqa: ARG002 world-wide
        self.step_dt = 1.0 / float(tick_hz)
        self.max_catch_up = float(max_catch_up)
        self.world.fixed_dt = self.step_dt

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

    def _op_noop(self, uid: int) -> None:
        """Do nothing; a command whose arrival wakes a blocked worker."""

    def _op_settle(self, uid: int, marker: threading.Event) -> None:
        self.markers.append(marker)

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
        """The world's index for a preset or defined name, a Material, or an index; -1 for none."""
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
        return int(self.world.add_material(material))

    def define_material(self, name: str, material: model.Material) -> int:
        """Make ``material`` the one called ``name``; the index it has in the world."""
        index = self._materials[name] = self.world.add_material(material)
        return index

    # -- stepping -------------------------------------------------------
    def step_frame(self, dt: float) -> int:
        """Add ``dt`` seconds, capped at the catch-up, and run the whole steps that fit.

        Returns how many steps ran. What is left of a step carries to the next call.
        """
        self._accumulator = min(self._accumulator + float(dt), self.max_catch_up)
        steps = 0
        while self._accumulator >= self.step_dt * (1.0 - _HAIR):
            self.step_once()
            self._accumulator = max(self._accumulator - self.step_dt, 0.0)
            steps += 1
        return steps

    @property
    def alpha(self) -> float:
        """How far through the next step the time left over from the last frame is, 0 to 1."""
        return min(self._accumulator / self.step_dt, 1.0)

    def step_once(self) -> None:
        """Run one fixed step, with its hooks, and collect the events it made."""
        world = self.world
        step = Step(self.step_dt, world.step_count, world.time)
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
        """Whether a step would change anything: a dynamic body is awake or a kinematic one moves."""
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
        """The poses and velocities of the bodies that move, ``alpha`` of the way through a step."""
        uids, indices, rows = self._mover_table()
        world = self.world
        self.version += 1
        if len(indices) == 0:
            empty3, empty4 = np.zeros((0, 3)), np.zeros((0, 4))
            flags = np.zeros(0, dtype=bool)
            return Snapshot(self.version, world.step_count, world.time, self.applied_seq, rows,
                            empty3, empty4, empty3, empty3, flags, flags)
        position = world.prev_position[indices] * (1.0 - alpha) + world.position[indices] * alpha
        if alpha >= 1.0:
            orientation = world.orientation[indices]
        else:
            orientation = mathutil.quat_normalize(
                world.prev_orientation[indices] * (1.0 - alpha)
                + world.orientation[indices] * alpha)
        return Snapshot(
            self.version, world.step_count, world.time, self.applied_seq, rows, position,
            mathutil.quat_to_axis_angle(orientation),
            world.linear_velocity[indices].copy(), world.angular_velocity[indices].copy(),
            world.awake[indices].copy(), world.motion_type[indices] == 2)

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
