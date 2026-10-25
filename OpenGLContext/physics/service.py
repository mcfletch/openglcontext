"""Physics: the service a context hosts for its rigid bodies.

One :class:`Physics` holds a world, steps it, and keeps it in step with the
scenegraph. The application adds bodies and reads and changes them through
:class:`~OpenGLContext.physics.body.Body` handles; it writes no tick code::

    body = physics.add_dynamic(ball, translation=(0, 4.5, -2), mass=2.0)
    body.apply_impulse((0, 0, 3))

The world is stepped by a worker, on a thread of its own or inline in the frame
hook (:mod:`OpenGLContext.physics.worker`). Changes travel to it as plain-data
commands; results come back once a frame in :meth:`Physics.frame`, which writes
poses onto the nodes, delivers events to their handlers and applies the scene
changes handlers queued from the worker. A ``Physics`` holds no GL and needs no
context, so a tool or a test builds one and steps it by hand with :meth:`step`.
"""
from __future__ import annotations

import collections
import concurrent.futures
import itertools
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from omi_physics import mathutil, model

from OpenGLContext.events.handoff import Updates
from OpenGLContext.physics.body import Body
from OpenGLContext.physics.callbacks import is_physics_callback
from OpenGLContext.physics.events import Collision
from OpenGLContext.physics.handlers import NAME_OF, STEP_EVENTS, Handler, HandlerTable
from OpenGLContext.physics.manager import write_pose
from OpenGLContext.physics.proxy import DEFAULT_DENSITY, Proxy
from OpenGLContext.physics.records import BodySpec, Command, PhysicsEvent, Step
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.worker import InlineWorker, ThreadWorker, Worker
from OpenGLContext.scenegraph.physicsbody import vrml_rotation_to_quat

__all__ = ['Physics']

log = logging.getLogger(__name__)

#: How many removed bodies are still named by events about their last contacts.
RETIRED_KEPT = 4096
_ZERO3 = np.zeros(3)


@dataclass(frozen=True, slots=True)
class _State:
    """A body's pose and velocity as one read found it."""
    position: np.ndarray
    axis_angle: np.ndarray
    velocity: np.ndarray
    angular_velocity: np.ndarray
    asleep: bool


class Physics:
    """The rigid-body world of one context, and the handles to what is in it."""

    def __init__(self, definition: PhysicsDefinition | None = None, *,
                 wake: Callable[[], Any] | None = None,
                 mark: Callable[..., Any] | None = None,
                 recording: Callable[[], bool] | None = None) -> None:
        definition = definition if definition is not None else PhysicsDefinition()
        definition.validate()
        self.definition = definition
        self._wake = wake
        #: ``mark(name, **fields)`` writes to the session journal, when ``recording()`` says one is kept.
        self._mark = mark
        self._recording = recording
        #: Scene changes the worker queues for the render thread (``render.set`` and ``render.call``).
        self.render = Updates(wake=wake)
        self.handlers = HandlerTable()
        self._uids = itertools.count(1)
        self._seq = itertools.count(1)
        self._bodies: dict[int, Body] = {}
        self._by_node: dict[Any, Body] = {}
        self._movers: list[Body] = []
        self._retired: collections.OrderedDict[int, Body] = collections.OrderedDict()
        self._snapshot: Any = None
        self._awake = False
        self._enabled = bool(definition.enabled)
        self._gravity = tuple(float(v) for v in definition.gravity)
        self._closed = False
        #: Removed bodies whose handlers end once the world has applied the removal
        #: and their last events are delivered: (command sequence, id).
        self._gone: list[tuple[int, int]] = []
        self.worker: Worker = self._make_worker(definition.mode, None)
        self._install_hooks()

    # -- the worker -----------------------------------------------------
    def _make_worker(self, mode: str, runtime: Any) -> Worker:
        if mode == 'inline':
            return InlineWorker(self.definition, runtime=runtime)
        return ThreadWorker(self.definition, wake=self._wake, runtime=runtime)

    def _install_hooks(self) -> None:
        runtime = self.worker.runtime
        runtime.on_events.append(self._on_worker_events)
        runtime.before_step.append(self._run_step_handlers('before-step'))
        runtime.after_step.append(self._run_step_handlers('after-step'))

    def _ensure_started(self) -> None:
        if self._enabled and not self._closed:
            self.worker.start()

    @property
    def world(self) -> Any:
        """The live :class:`omi_physics.world.PhysicsWorld`, in inline mode only.

        A world stepped on a thread is reached with :meth:`run`.
        """
        if isinstance(self.worker, InlineWorker):
            return self.worker.runtime.world
        raise RuntimeError('physics.world is for inline mode; use physics.run(fn) to reach '
                           'the world on its thread')

    # -- configuration --------------------------------------------------
    def set_config(self, definition: PhysicsDefinition) -> None:
        """Apply ``definition`` between ticks: gravity, the step, damping and the mode.

        Bodies stay as they are. Raises ValueError, changing nothing, for a
        definition the service cannot run.
        """
        definition.validate()
        previous, self.definition = self.definition, definition
        self._send_world('config', float(definition.tickHz), float(definition.maxCatchUp))
        self.gravity = tuple(definition.gravity)
        self._enabled = bool(definition.enabled)
        if definition.mode != previous.mode:
            self._switch(definition.mode)
        elif not self._enabled:
            self.worker.stop()
        elif self._movers:
            self._ensure_started()

    def _switch(self, mode: str) -> None:
        old = self.worker
        old.stop()
        pending = old.inbox.drain()
        new = self._make_worker(mode, old.runtime)
        for command in pending:
            new.inbox.post(command)
        self.worker = new
        if self._movers:
            self._ensure_started()

    def enable(self, on: bool = True, tick_frequency: float | None = None) -> None:
        """Run the world, or pause it with every body where it is.

        ``tick_frequency`` sets the step, in steps a second, from now on.
        """
        if tick_frequency is not None:
            if not tick_frequency > 0.0:
                raise ValueError('tick_frequency must be above zero, not %r' % (tick_frequency,))
            self.definition.tickHz = float(tick_frequency)
            self._send_world('config', float(tick_frequency), float(self.definition.maxCatchUp))
        self._enabled = bool(on)
        if not self._enabled:
            self.worker.stop()
        elif self._movers:
            self._ensure_started()

    @property
    def gravity(self) -> tuple[float, ...]:
        """Gravity as an acceleration in metres a second squared."""
        return self._gravity

    @gravity.setter
    def gravity(self, vector: Iterable[float]) -> None:
        self._gravity = tuple(float(v) for v in vector)
        self._send_world('gravity', self._gravity)

    # -- adding bodies --------------------------------------------------
    def add_static(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body that never moves and stops what meets it."""
        return self._add('static', node, proxy, options)

    def add_dynamic(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body the world moves: it falls, collides and answers pushes.

        Options: ``mass`` in kilograms (default from the shape's volume and
        ``density``), ``density``, ``translation`` and ``rotation`` to place the
        node first, ``material`` (a preset or defined name or a
        :class:`~omi_physics.model.Material`), ``friction``, ``restitution``,
        ``linear_damping``, ``angular_damping`` and ``collision_filter``.
        """
        return self._add('dynamic', node, proxy, options)

    def add_kinematic(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body moved by code that pushes dynamic bodies and is never pushed."""
        return self._add('kinematic', node, proxy, options)

    def add_trigger(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a volume that reports what enters and leaves it and stops nothing."""
        return self._add('trigger', node, proxy, options)

    _OPTIONS = frozenset({'mass', 'density', 'translation', 'rotation', 'material', 'friction',
                          'restitution', 'linear_damping', 'angular_damping', 'collision_filter'})

    def _add(self, kind: str, node: Any, proxy: Any, options: dict[str, Any]) -> Body:
        unknown = set(options) - self._OPTIONS
        if unknown:
            raise TypeError('unknown option %s for add_%s' % (', '.join(sorted(unknown)), kind))
        if options.get('translation') is not None:
            node.translation = tuple(options['translation'])
        if options.get('rotation') is not None:
            node.rotation = tuple(options['rotation'])
        shape = self._proxy(node, proxy, kind)
        position = np.asarray(node.translation, dtype='d')[:3]
        axis_angle = np.asarray(node.rotation, dtype='d')[:4]
        dynamic = kind == 'dynamic'
        mass = 0.0
        if dynamic:
            mass = float(options['mass']) if options.get('mass') is not None else shape.mass(
                float(options.get('density') or DEFAULT_DENSITY))
        linear = options.get('linear_damping')
        angular = options.get('angular_damping')
        motion = model.Motion(
            type={'dynamic': model.DYNAMIC, 'kinematic': model.KINEMATIC}.get(kind, model.STATIC),
            mass=mass if dynamic else 1.0,
            linearDamping=float(self.definition.linearDamping if linear is None else linear),
            angularDamping=float(self.definition.angularDamping if angular is None else angular))
        uid = next(self._uids)
        spec = BodySpec(uid, kind, shape, motion, tuple(position),
                        tuple(vrml_rotation_to_quat(axis_angle)), self._material(options),
                        int(options.get('collision_filter', -1)))
        body = Body(self, uid, kind, node, shape, position, axis_angle, mass,
                    motion.linearDamping, motion.angularDamping)
        self._bodies[uid] = body
        self._by_node[node] = body
        if kind in ('dynamic', 'kinematic'):
            self._movers.append(body)
        if self._enabled and not self._closed:
            self.worker.submit(Command('add', uid, (spec,), next(self._seq)))
            if kind in ('dynamic', 'kinematic'):
                self._ensure_started()
        return body

    @staticmethod
    def _material(options: dict[str, Any]) -> Any:
        friction, restitution = options.get('friction'), options.get('restitution')
        if friction is None and restitution is None:
            return options.get('material')
        base = model.MATERIAL_PRESETS.get(options.get('material') or '', model.Material())
        return model.Material(
            staticFriction=base.staticFriction if friction is None else float(friction),
            dynamicFriction=base.dynamicFriction if friction is None else float(friction),
            restitution=base.restitution if restitution is None else float(restitution),
            frictionCombine=base.frictionCombine, restitutionCombine=base.restitutionCombine)

    def _proxy(self, node: Any, proxy: Any, kind: str) -> Proxy:
        dynamic = kind in ('dynamic', 'kinematic')
        if isinstance(proxy, Proxy):
            return proxy
        if proxy is None:
            return Proxy.from_node(node, 'auto', dynamic)
        if isinstance(proxy, str):
            return Proxy.from_node(node, proxy, dynamic)
        if isinstance(proxy, model.Shape):
            return Proxy(proxy)
        return Proxy.from_node(proxy, 'auto', dynamic)

    def cook(self, node: Any, strategy: str = 'auto', dynamic: bool = True) -> Proxy:
        """A :class:`Proxy` cooked from what ``node`` draws, to share between bodies."""
        return Proxy.from_node(node, strategy, dynamic)

    def remove(self, body: Body) -> None:
        """Take ``body`` out of the world. Removing twice is harmless."""
        if not body.alive:
            return
        if self._enabled and not self._closed:
            seq = next(self._seq)
            self.worker.submit(Command('remove', body.uid, (), seq))
            self._gone.append((seq, body.uid))
        else:
            self.handlers.forget_body(body.uid)
        body.alive = False
        self._bodies.pop(body.uid, None)
        if self._by_node.get(body.node) is body:
            del self._by_node[body.node]
        if body in self._movers:
            self._movers.remove(body)
        self._retired[body.uid] = body
        while len(self._retired) > RETIRED_KEPT:
            self._retired.popitem(last=False)

    def body_for(self, node: Any, within: Any = None) -> Body | None:
        """The body of ``node``, or None.

        With ``within``, a node under it, the nearest ancestor on the way down
        that has a body answers for a node that has none itself.
        """
        found = self._by_node.get(node)
        if found is not None or within is None:
            return found
        path = _path_to(within, node)
        for ancestor in reversed(path or ()):
            found = self._by_node.get(ancestor)
            if found is not None:
                return found
        return None

    def bodies_in(self, group: Any) -> list[Body]:
        """The bodies of the nodes at and under ``group``, in the order they are met."""
        found: list[Body] = []
        stack = [group]
        while stack:
            node = stack.pop()
            body = self._by_node.get(node)
            if body is not None:
                found.append(body)
            stack.extend(reversed(list(getattr(node, 'children', None) or ())))
        return found

    # -- commands ---------------------------------------------------------
    def _command(self, op: str, body: Body, *args: Any) -> int:
        if not body.alive or not self._enabled or self._closed:
            return 0
        seq = next(self._seq)
        self.worker.submit(Command(op, body.uid, args, seq))
        return seq

    def _send_world(self, op: str, *args: Any) -> None:
        if not self._closed:
            self.worker.submit(Command(op, 0, args, next(self._seq)))

    def run(self, function: Callable[[Any], Any]) -> concurrent.futures.Future[Any]:
        """Call ``function(world)`` on the worker with the raw world; the future holds its answer.

        This reaches what the service has no name for: joints, contact filters,
        reads of world arrays. A world with no thread running is reached on the
        calling thread, at once.
        """
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._send_world('run', function, future)
        self.worker.flush()
        return future

    def post(self, function: Callable[..., Any], *arguments: Any) -> None:
        """Call ``function(*arguments)`` on the worker, once its thread next steps; returns None."""
        self._send_world('post', function, arguments)

    # -- the frame ----------------------------------------------------------
    def step(self, dt: float) -> None:
        """Advance the world by ``dt`` seconds by hand, for a service nothing else steps."""
        self.worker.step(dt)

    def frame(self, dt: float) -> bool:
        """Do the render thread's share of one frame; True if the scene changed or is still moving.

        Takes what the worker has published, writes poses onto the nodes of
        bodies that move, delivers events to render-thread handlers and applies
        the scene changes handlers queued from the worker. An inline worker
        steps ``dt`` seconds first.
        """
        if not self._enabled or self._closed:
            self.render.apply()
            return False
        out = self.worker.collect(dt)
        wrote = False
        if out.snapshot is not None:
            self._snapshot = out.snapshot
            wrote = self._write_poses(out.snapshot)
            moving = out.snapshot.awake & (out.snapshot.dynamic | (
                np.abs(out.snapshot.linear_velocity).sum(axis=1) > 0.0))
            self._awake = bool(moving.any())
        if out.events:
            self._dispatch(out.events)
        self._finish_removals()
        applied = self.render.apply()
        return bool(self._awake or applied or wrote and self._awake)

    def _finish_removals(self) -> None:
        """End the handlers of the bodies the world has now removed and told its last events of."""
        if not self._gone:
            return
        applied = 0 if self._snapshot is None else self._snapshot.applied_seq
        waiting = []
        for seq, uid in self._gone:
            if seq <= applied:
                self.handlers.forget_body(uid)
            else:
                waiting.append((seq, uid))
        self._gone = waiting

    def _write_poses(self, snapshot: Any) -> bool:
        wrote = False
        rows = snapshot.rows
        for body in self._movers:
            row = rows.get(body.uid)
            if row is None:
                continue
            placed = body._placed
            if placed is not None:
                if snapshot.applied_seq < placed[0]:
                    continue
                body._placed = None
            if body.kind == 'dynamic' and not snapshot.awake[row]:
                continue
            write_pose(body.node, snapshot.position[row], snapshot.axis_angle[row])
            wrote = True
        return wrote

    # -- reading ----------------------------------------------------------
    def _state(self, body: Body) -> _State:
        state = self._live_state(body) if self.worker.on_worker_thread() else self._published_state(body)
        placed = body._placed
        if placed is not None and (self._snapshot is None
                                   or self._snapshot.applied_seq < placed[0]):
            position = state.position if placed[1] is None else placed[1]
            axis_angle = state.axis_angle if placed[2] is None else placed[2]
            return _State(position, axis_angle, state.velocity, state.angular_velocity,
                          state.asleep)
        return state

    def _live_state(self, body: Body) -> _State:
        runtime = self.worker.runtime
        if body.uid not in runtime:
            return self._published_state(body)
        world = runtime.world
        index = runtime.entry(body.uid).index
        axis_angle = mathutil.quat_to_axis_angle(world.orientation[index][None])[0]
        return _State(world.position[index].copy(), axis_angle,
                      world.linear_velocity[index].copy(), world.angular_velocity[index].copy(),
                      not bool(world.awake[index]))

    def _published_state(self, body: Body) -> _State:
        snapshot = self._snapshot
        row = None if snapshot is None else snapshot.rows.get(body.uid)
        if snapshot is None or row is None:
            return _State(body._position, body._axis_angle, _ZERO3, _ZERO3, False)
        return _State(snapshot.position[row], snapshot.axis_angle[row],
                      snapshot.linear_velocity[row], snapshot.angular_velocity[row],
                      not bool(snapshot.awake[row]) and bool(snapshot.dynamic[row]))

    # -- events -------------------------------------------------------------
    def addEventHandler(self, event: str, function: Callable[..., Any] | None = None,
                        **filters: Any) -> Handler | None:
        """Call ``function`` for each ``event`` that happens to any body.

        See :meth:`Body.addEventHandler <OpenGLContext.physics.body.Body.addEventHandler>`
        for the events and filters. ``'before-step'`` and ``'after-step'`` call
        ``function(step)`` around every fixed step and need a function marked
        :func:`~OpenGLContext.physics.callbacks.physics_callback`.
        """
        return self._add_handler(event, function, None, **filters)

    def _add_handler(self, event: str, function: Callable[..., Any] | None,
                     bodies: Iterable[Body] | None, **filters: Any) -> Handler | None:
        unknown = set(filters) - {'above', 'other'}
        if unknown:
            raise TypeError('unknown filter %s' % ', '.join(sorted(unknown)))
        uids = None if bodies is None else [body.uid for body in bodies]
        if function is None:
            for handler in self.handlers.named(event, uids):
                handler.cancel()
            return None
        if event in STEP_EVENTS and not is_physics_callback(function):
            raise ValueError('%s handlers run inside the step; mark the function with '
                             '@physics_callback' % event)
        other = filters.get('other')
        other_uids = None
        if other is not None:
            other_uids = [other.uid] if isinstance(other, Body) else [item.uid for item in other]
        handler = Handler(event, function, uids, other_uids, float(filters.get('above', 0.0)))
        self.handlers.add(handler)
        self._report_for(handler)
        return handler

    def _report_for(self, handler: Handler) -> None:
        if handler.event in STEP_EVENTS:
            return
        self._send_world('logging', True)
        if handler.kind == 'state':
            self._send_world('state_events', True)
            return
        if handler.bodies is None:
            self._send_world('report_all', True)
        else:
            for uid in handler.bodies:
                if uid in self._bodies:
                    self.worker.submit(Command('report', uid, (True,), next(self._seq)))
        if handler.phase in ('persist', 'stay'):
            self._send_world('persist', True)

    def _collision(self, event: PhysicsEvent, side: int) -> Collision:
        first, second = self._body_of(event.a), self._body_of(event.b)
        mine, theirs = (first, second) if side == 0 else (second, first)
        if event.kind == 'contact':
            normal = -event.normal if side == 0 else event.normal
        else:
            normal = _ZERO3
        return Collision(
            event.kind, event.phase, mine, theirs, getattr(mine, 'node', None),
            getattr(theirs, 'node', None), event.point, normal, event.approach, event.impulse,
            event.friction_impulse, event.slip, event.depth, event.time, event.solved,
            event.reason, event.payload, event, event.step)

    def _body_of(self, uid: int | None) -> Body | None:
        if uid is None:
            return None
        found = self._bodies.get(uid)
        return found if found is not None else self._retired.get(uid)

    def _journal(self, event: PhysicsEvent) -> None:
        """Write ``event`` to the session journal: what happened, to which bodies, and when."""
        name = NAME_OF.get((event.kind, event.phase))
        if name is None or self._mark is None:
            return
        fields: dict[str, Any] = {'step': event.step, 'time': round(float(event.time), 6),
                                  'a': self._label(event.a)}
        if event.b is not None:
            fields['b'] = self._label(event.b)
        if event.kind == 'contact':
            fields['approach'] = round(float(event.approach), 4)
            fields['impulse'] = round(float(event.impulse), 3)
        self._mark('physics-' + name, **fields)

    def _label(self, uid: int) -> str:
        """How the journal names a body: its node's DEF name, else the order it was added in."""
        body = self._body_of(uid)
        given = getattr(getattr(body, 'node', None), 'DEF', None)
        return str(given) if given else '#%d' % uid

    def _dispatch(self, events: Iterable[PhysicsEvent]) -> None:
        journal = self._mark is not None and self._recording is not None and self._recording()
        for event in events:
            if journal and (self.handlers.audience(event, physics=False)
                            or self.handlers.audience(event, physics=True)):
                self._journal(event)
            for handler, side in self.handlers.audience(event, physics=False):
                self._call(handler, self._collision(event, side))
        self.handlers.prune()

    def _on_worker_events(self, events: Iterable[PhysicsEvent]) -> None:
        for event in events:
            for handler, side in self.handlers.audience(event, physics=True):
                self._call(handler, self._collision(event, side))

    def _run_step_handlers(self, name: str) -> Callable[[Step], None]:
        def run(step: Step) -> None:
            for handler in self.handlers.of_step(name):
                function = handler.function()
                if function is None:
                    handler.cancel()
                    continue
                self._invoke(handler, function, step)
        return run

    def _call(self, handler: Handler, collision: Collision) -> None:
        function = handler.function()
        if function is None:
            handler.cancel()
            return
        self._invoke(handler, function, collision)

    @staticmethod
    def _invoke(handler: Handler, function: Callable[..., Any], argument: Any) -> None:
        try:
            function(argument)
        except Exception:
            if not handler.failed:
                handler.failed = True
                log.exception('physics handler %r failed on %r', function, argument)

    # -- accounting ---------------------------------------------------------
    @property
    def error(self) -> BaseException | None:
        """The exception that stopped the worker, or None."""
        return getattr(self.worker, 'error', None)

    def close(self) -> None:
        """Stop the worker and let go of the bodies. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self.worker.stop()


def _path_to(root: Any, target: Any) -> list[Any] | None:
    """The nodes from ``root`` down to ``target``, or None when ``target`` is not under it."""
    stack: list[tuple[Any, list[Any]]] = [(root, [root])]
    while stack:
        node, path = stack.pop()
        if node is target:
            return path
        for child in getattr(node, 'children', None) or ():
            stack.append((child, [*path, child]))
    return None

