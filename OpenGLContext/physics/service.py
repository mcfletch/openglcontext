"""Physics: the service a context hosts for its rigid bodies.

One :class:`Physics` holds a world, steps it, and keeps it in step with the
scenegraph. The application adds bodies and reads and changes them through
:class:`~OpenGLContext.physics.body.Body` handles; it writes no tick code::

    body = physics.add_dynamic(ball, translation=(0, 4.5, -2), mass=2.0)
    body.apply_impulse((0, 0, 3))

The world is stepped by an engine (:mod:`OpenGLContext.physics.engine`):
omi_physics on a thread of its own or inline in the frame hook, or Jolt on
pyjoltphysics' world thread, free-running or in lockstep with the frame
(``PhysicsDefinition.engine``). Changes travel to it as plain-data
commands; results come back once a frame in :meth:`Physics.frame`, which writes
poses onto the nodes, delivers events to their handlers and applies the scene
changes handlers queued from the worker. A ``Physics`` holds no GL and needs no
context, so a tool or a test builds one and steps it by hand with :meth:`step`.
"""
from __future__ import annotations

import collections
import concurrent.futures
import dataclasses
import itertools
import logging
import os
import queue
import time
import weakref
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from OpenGLContext.events.framestep import FixedSteps
from OpenGLContext.events.handoff import Updates
from OpenGLContext.physics.body import Body
from OpenGLContext.physics.character import Character, stand_in_proxy
from OpenGLContext.physics.engine import Engine, make_engine
from OpenGLContext.physics.checks import number, vector
from OpenGLContext.physics.callbacks import is_physics_callback
from OpenGLContext.physics.colliders import SceneryTracker
from OpenGLContext.physics.events import Collision
from OpenGLContext.physics.filters import Approach, Filters
from OpenGLContext.physics.handlers import NAME_OF, STEP_EVENTS, Handler, HandlerTable
from OpenGLContext.physics.joints import READINGS, Joint, make_joint
from OpenGLContext.physics.materials import Materials
from OpenGLContext.physics.poses import quat_to_vrml_rotation, vrml_rotation_to_quat, write_poses
from OpenGLContext.physics.proxy import DEFAULT_DENSITY, Proxy
from OpenGLContext.physics.records import (
    BodyBatch, BodySpec, Command, Motion, PhysicsEvent, Snapshot, Step,
)
from OpenGLContext.physics.sources import SourceHandle
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.stepview import StepHook, StepView
from OpenGLContext.physics.types import (
    CharacterCapabilities, EngineInfo, GravityZone, Hit, Material, Poses, WorldCounts,
)

__all__ = ['Physics']

log = logging.getLogger(__name__)

#: How many removed bodies are still named by events about their last contacts.
RETIRED_KEPT = 4096
_ZERO3 = np.zeros(3)
#: The closing speed, in metres a second, a strike must exceed to make the sound of its material.
SOUND_SPEED = 1.0
#: The closing speed that plays a material's sound at full gain.
SOUND_FULL = 6.0


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
                 recording: Callable[[], bool] | None = None,
                 audio: Callable[[], Any] | None = None,
                 mount: Callable[[Any, bool], Any] | None = None,
                 render_thread: int | None = None) -> None:
        definition = definition if definition is not None else PhysicsDefinition()
        definition.validate()
        self.definition = definition
        self._wake = wake
        #: ``mark(name, **fields)`` writes to the session journal, when ``recording()`` says one is kept.
        self._mark = mark
        self._recording = recording
        #: Gives the context's audio, asked only when a material's sound is to be played.
        self._audio = audio
        #: ``mount(node, True)`` puts a node in the scene and ``mount(node, False)`` takes it out.
        self._mount = mount
        self._overlay: Any = None
        self._zones_placed: tuple[Any, ...] = ()
        self.materials = Materials(self)
        #: The collision filters sent to the world (``collision_filter=`` of the ``add_*`` calls).
        self.filters = Filters(lambda index, given: self._send_world('filter', index, given))
        #: Scene changes the worker queues for the render thread (``render.set`` and ``render.call``).
        self.render = Updates(wake=wake, owner=render_thread)
        self.handlers = HandlerTable()
        self._uids = itertools.count(1)
        self._seq = itertools.count(1)
        self._bodies: dict[int, Body] = {}
        self._by_node: dict[Any, Body] = {}
        self._movers: list[Body] = []
        self._retired: collections.OrderedDict[int, Body] = collections.OrderedDict()
        self._snapshot: Snapshot | None = None
        #: The body at each row of the snapshot row table ``_posed_rows``, the version
        #: whose poses the nodes hold, and rows held back for a pending place.
        self._pose_rows: list[Body | None] = []
        self._posed_rows: dict[int, int] | None = None
        self._posed_version: int | None = None
        self._held: list[int] = []
        self._awake = False
        self._enabled = bool(definition.enabled)
        self._gravity = tuple(float(v) for v in definition.gravity)
        self._closed = False
        #: Whether the world is held inline whatever the definition's mode (:meth:`pin_inline`).
        self._pinned = False
        #: The last failure logged for each source and character (:meth:`_guarded`).
        self._failures: weakref.WeakKeyDictionary[Any, tuple[type, str]] = weakref.WeakKeyDictionary()
        #: The worker error :meth:`frame` has raised, so it is raised once.
        self._raised: BaseException | None = None
        #: Removed bodies whose handlers end once the world has applied the removal
        #: and their last events are delivered: (command sequence, id).
        self._gone: list[tuple[int, int]] = []
        #: The engine that steps the world (:mod:`OpenGLContext.physics.engine`).
        self._engine: Engine = make_engine(definition, wake=wake)
        self._install_hooks()
        self.scenery = SceneryTracker(self)
        #: The spec of each body in the world, to build the replica from when queries need it.
        self._specs: dict[int, BodySpec] = {}
        self._replica: Any = None
        self._characters: list[Character] = []
        #: The fixed steps the characters owe each frame where the world steps on its own thread.
        self._character_clock = FixedSteps(1.0 / float(definition.tickHz),
                                           float(definition.maxCatchUp))
        #: For each character's stand-in, by id, the fixed triggers and sensors near it
        #: (:meth:`_fixed_seen`).
        self._seen_gathers: dict[int, tuple[Any, tuple[float, ...], tuple[float, ...],
                                            list[tuple[float, ...]]]] = {}
        #: The bodies that characters walk through, by id.
        self._passable: set[int] = set()
        self._sources: list[SourceHandle] = []
        self._cooker: concurrent.futures.ThreadPoolExecutor | None = None
        self._cooked_results: queue.SimpleQueue[tuple[Body, BodySpec | None]] = queue.SimpleQueue()
        self._outstanding = 0
        #: How many scenery shapes have been cooked.
        self.cooked = 0
        #: The functions :meth:`on_step` registered, called after each step.
        self._step_hooks: list[StepHook] = []
        self._zone_ids = itertools.count(1)

    # -- the engine -----------------------------------------------------
    @property
    def worker(self) -> Any:
        """The omi engine's worker, which steps its world; on another engine, the engine."""
        return getattr(self._engine, 'worker', self._engine)

    def _install_hooks(self) -> None:
        engine = self._engine
        engine.on_events.append(self._on_worker_events)
        engine.before_step.append(self._run_step_handlers('before-step'))
        engine.after_step.append(self._run_step_handlers('after-step'))
        engine.wants_steps.append(self.handlers.has_step_handlers)
        if engine.stand_ins:
            engine.before_step.append(self._settle_stand_ins)
            engine.wants_steps.append(self._stand_ins_want_steps)
            engine.replica = self._character_replica
        engine.material_of = lambda name: self.materials.get(name).material
        engine.body_of = self._body_of
        engine.framed_characters = lambda: [one for one in self._characters if one.framed]
        engine.guard = self._guarded
        engine.wants_events = self.handlers.has_physics_handlers
        engine.after_step.append(self._run_step_hooks)
        engine.wants_steps.append(self._step_hooks_want_steps)

    def _ensure_started(self) -> None:
        if self._enabled and not self._closed:
            self._engine.start()

    @property
    def _omi(self) -> Any:
        """The omi engine; RuntimeError on another engine, which has no omi_physics world."""
        engine = self._engine
        if engine.name != 'omi':
            raise RuntimeError('this reads the omi_physics world, and the world is stepped by '
                               'the %s engine; read bodies with physics.poses and run '
                               'tick-exact code with physics.on_step' % (engine.name,))
        return engine

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    @property
    def engine(self) -> EngineInfo:
        """The engine that steps the world: its name, version, step rate and precision."""
        return self._engine.info()

    @property
    def counts(self) -> WorldCounts:
        """How many bodies the world holds and how many pairs touch, as its last published step left them.

        Both are 0 before the world has published a step.
        """
        return self._engine.counts(self._snapshot)

    def _engine_world(self) -> Any:
        """The engine's world of an inline service, with each waiting stand-in written."""
        worker = self._inline()
        self._bring_up_all()
        return worker.runtime.world

    def _inline(self) -> Any:
        """The omi worker, where it steps inline; RuntimeError where it has a thread."""
        if self._omi.mode == 'inline':
            return self._omi.worker
        raise RuntimeError('the engine\'s world is read inline only; a world on its own thread '
                           'is read with physics.poses and physics.on_step')

    def _slot_of(self, body: Body) -> int:
        """The row ``body`` has in the engine's arrays; KeyError for a body the world does not hold."""
        worker = self._inline()
        self._bring_up_all()
        worker.flush()
        return int(worker.runtime.entry(body.uid).index)

    def _body_at(self, slot: int) -> Body | None:
        """The body in row ``slot`` of the engine's arrays, or None for a row no body has."""
        worker = self._inline()
        self._bring_up_all()
        world = worker.runtime.world
        if not 0 <= slot < len(world.bodies):
            return None
        uid = world.handle_of(world.ref(slot))
        return None if uid is None else self._bodies.get(int(uid))

    # -- configuration --------------------------------------------------
    def set_config(self, definition: PhysicsDefinition) -> None:
        """Apply ``definition`` between ticks: gravity, the step, damping and the mode.

        Bodies stay as they are. A new ``backend`` is used from the next step;
        one that cannot be made logs a warning and the world keeps the one it
        has (:attr:`engine` names it). A world held inline by :meth:`pin_inline` keeps
        stepping inline and takes the new mode when it is let go. Raises
        ValueError, changing nothing, for a definition the service cannot run.
        """
        definition.validate()
        self._bring_up_all()
        if definition.engine != self.definition.engine:
            raise ValueError('the engine is chosen when the service is made; this one runs %s'
                             % (self.definition.engine,))
        if definition.backend != self.definition.backend:
            self._send_world('backend', str(definition.backend))
        self.definition = definition
        self._send_world('config', float(definition.tickHz), float(definition.maxCatchUp))
        self.gravity = tuple(definition.gravity)
        self._enabled = bool(definition.enabled)
        if self._mode() != self._worker_mode():
            self._switch(self._mode())
        elif not self._enabled:
            self._engine.stop()
        elif self._movers:
            self._ensure_started()

    def pin_inline(self, on: bool = True) -> None:
        """Hold the world inline whatever the definition's mode, or let it go back to that mode.

        A recorded session and a capture hold it inline, so the world is a
        function of the clock and of the commands. Commands waiting for a
        thread's world are carried over, in order. A world held inline waits
        for its scenery's cooking before each step: scenery the render pass
        finds while drawing one frame is in the world for the next frame's step.
        """
        self._pinned = bool(on)
        self._engine.pin(self._pinned)
        if self._mode() != self._worker_mode():
            self._switch(self._mode())

    def _mode(self) -> str:
        """The mode the world steps in: inline while pinned, else the definition's."""
        return 'inline' if self._pinned else self.definition.mode

    def _worker_mode(self) -> str:
        return self._engine.mode

    def _switch(self, mode: str) -> None:
        """Step the world in ``mode`` from now on, carrying the waiting commands over in order.

        Raises RuntimeError, leaving the worker as it is, where its thread is
        still in a step once the worker's stop has waited for it.
        """
        self._bring_up_all()
        self._engine.set_mode(mode)
        if self._movers:
            self._ensure_started()

    def enable(self, on: bool = True, tick_frequency: float | None = None) -> None:
        """Run the world, or pause it with every body where it is.

        A paused world takes no steps. Bodies added or removed, writes and
        joints made while it is paused are kept in order and reach the world
        when it runs again. ``tick_frequency`` sets the step, in steps a
        second, from now on.
        """
        if tick_frequency is not None:
            self.definition.tickHz = number(tick_frequency, 'tick_frequency', positive=True)
            self._send_world('config', float(tick_frequency), float(self.definition.maxCatchUp))
        self._bring_up_all()
        self._enabled = bool(on)
        if not self._enabled:
            self._engine.stop()
        elif self._movers:
            self._ensure_started()

    @property
    def gravity(self) -> tuple[float, ...]:
        """Gravity as an acceleration in metres a second squared."""
        return self._gravity

    @gravity.setter
    def gravity(self, value: Iterable[float]) -> None:
        self._gravity = vector(value, 'gravity')
        self._send_world('gravity', self._gravity)

    @property
    def time(self) -> float:
        """The world's clock: the seconds of fixed steps it has taken, as last published.

        Inside a step's handlers it is the live clock, the time that step began,
        which is the ``time`` of the :class:`~OpenGLContext.physics.records.Step`
        they are given. A world that is not busy is not stepped, so its clock
        stands while nothing moves.
        """
        if self._engine.on_engine_thread():
            return self._engine.live_time()
        snapshot = self._snapshot
        return 0.0 if snapshot is None else float(snapshot.time)

    # -- adding bodies --------------------------------------------------
    def add_static(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body that never moves and stops what meets it.

        ``node`` is None for a body that is only a shape, such as a level cooked
        elsewhere: ``physics.add_static(None, proxy=Proxy.trimesh(points, indices))``.
        The other ``add_*`` calls take None the same way, and ``translation=`` and
        ``rotation=`` place the body.
        """
        return self._add('static', node, proxy, options)

    def add_dynamic(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body the world moves: it falls, collides and answers pushes.

        Options: ``mass`` in kilograms (default from the shape's volume and
        ``density``), ``density``, ``translation`` and ``rotation`` to place the
        node first, ``material`` (a preset or defined name or a
        :class:`~OpenGLContext.physics.types.Material`), ``friction``, ``restitution``,
        ``linear_damping``, ``angular_damping``, ``gravity_factor`` (1 by default;
        see :meth:`Body.set_gravity_factor`) and ``collision_filter``.
        """
        return self._add('dynamic', node, proxy, options)

    def add_kinematic(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a body moved by code that pushes dynamic bodies and is never pushed."""
        return self._add('kinematic', node, proxy, options)

    def add_trigger(self, node: Any, proxy: Any = None, **options: Any) -> Body:
        """Make ``node`` a volume that reports what enters and leaves it and stops nothing."""
        return self._add('trigger', node, proxy, options)

    _OPTIONS = frozenset({'mass', 'density', 'translation', 'rotation', 'material', 'friction',
                          'restitution', 'linear_damping', 'angular_damping', 'collision_filter',
                          'blocks_characters', 'gravity_factor'})

    def _add(self, kind: str, node: Any, proxy: Any, options: dict[str, Any], *,
             motion: Motion | None = None,
             pose: tuple[tuple[float, ...], tuple[float, ...]] | None = None,
             derived: bool = False) -> Body:
        """Make a body of ``kind`` for ``node``.

        ``motion`` replaces the motion the options describe, ``pose`` is a world
        position and quaternion in place of the node's own, and ``derived`` marks
        a body the service made from the scene rather than one the application added.
        """
        unknown = set(options) - self._OPTIONS
        if unknown:
            raise TypeError('unknown option %s for add_%s' % (', '.join(sorted(unknown)), kind))
        options = _checked(options)
        if node is None:
            if not isinstance(proxy, Proxy):
                raise TypeError('a body with no node needs a shape: proxy=Proxy.box(...), '
                                'Proxy.trimesh(...) or another Proxy constructor')
            shape = proxy
            at, turned = options.get('translation'), options.get('rotation')
            position = np.asarray(_ZERO3 if at is None else at, dtype='d')[:3]
            axis_angle = np.asarray((0.0, 0.0, 1.0, 0.0) if turned is None else turned,
                                    dtype='d')[:4]
        else:
            if options.get('translation') is not None:
                node.translation = tuple(options['translation'])
            if options.get('rotation') is not None:
                node.rotation = tuple(options['rotation'])
            self._claim(node)
            shape = self._proxy(node, proxy, kind)
            position = np.asarray(node.translation, dtype='d')[:3]
            axis_angle = np.asarray(node.rotation, dtype='d')[:4]
        quaternion = tuple(vrml_rotation_to_quat(axis_angle))
        if pose is not None:
            position = np.asarray(pose[0], dtype='d')
            quaternion = pose[1]
            axis_angle = quat_to_vrml_rotation(quaternion)
        dynamic = kind == 'dynamic'
        linear = options.get('linear_damping')
        angular = options.get('angular_damping')
        factor = options.get('gravity_factor')
        factor = 1.0 if factor is None else factor
        if motion is None:
            mass = 0.0
            if dynamic:
                mass = options['mass'] if options.get('mass') is not None else shape.mass(
                    options.get('density') or DEFAULT_DENSITY)
            motion = Motion(
                mass if dynamic else 1.0,
                float(self.definition.linearDamping if linear is None else linear),
                float(self.definition.angularDamping if angular is None else angular), factor)
        mass = float(motion.mass) if dynamic else 0.0
        uid = next(self._uids)
        material = self._material(options)
        named = options.get('material') if isinstance(options.get('material'), str) else None
        sounding = self.materials.sound_of(named) is not None
        spec = BodySpec(uid, kind, shape, motion, tuple(position), quaternion, material,
                        self.filters.index(options.get('collision_filter')), report=sounding)
        body = Body(self, uid, kind, node, shape, position, axis_angle, mass,
                    motion.linear_damping, motion.angular_damping, motion.gravity_factor)
        body.derived = derived
        body.material = named
        body._surface = self._coefficients(material)
        if sounding:
            self._send_world('logging', True)
        self._bodies[uid] = body
        if node is not None:
            self._by_node[node] = body
        if kind in ('dynamic', 'kinematic'):
            self._movers.append(body)
        if not self._closed:
            self._send(Command('add', uid, (spec,), next(self._seq)))
            if kind in ('dynamic', 'kinematic'):
                self._ensure_started()
            if not options.get('blocks_characters', True):
                self._passable.add(uid)
                self._let_characters_through(uid)
        return body

    def _let_characters_through(self, uid: int) -> None:
        """Have the controllers of the characters walk through body ``uid``."""
        if not self._engine.stand_ins:
            for character in self._characters:
                character._controller.ignore.add(uid)
            return
        replica = self._replica
        if replica is not None and uid in replica:
            for character in self._characters:
                character._controller.ignore.add(replica.index_of(uid))

    def passable_slots(self) -> list[int]:
        """The slots, in the render thread's copy of the bodies, of the bodies characters walk through.

        On an engine with no stand-ins, the bodies' uids.
        """
        if not self._engine.stand_ins:
            return sorted(self._passable)
        replica = self._character_replica()
        return [replica.index_of(uid) for uid in self._passable if uid in replica]

    def _claim(self, node: Any) -> None:
        """Remove the scenery bodies made for ``node`` and for the shapes under it."""
        stack = [node]
        while stack:
            current = stack.pop()
            body = self._by_node.get(current)
            if body is not None and body.derived:
                self.remove(body)
            stack.extend(getattr(current, 'children', None) or ())

    def _material(self, options: dict[str, Any]) -> Any:
        given = options.get('material')
        if isinstance(given, str):
            self.materials.get(given)
        friction, restitution = options.get('friction'), options.get('restitution')
        if friction is None and restitution is None:
            return given
        known = self.materials._known.get(given) if isinstance(given, str) else None
        base = known.material if known is not None else (
            Material() if given is None else Material.coerce(given))
        return Material(
            staticFriction=base.staticFriction if friction is None else float(friction),
            dynamicFriction=base.dynamicFriction if friction is None else float(friction),
            restitution=base.restitution if restitution is None else float(restitution),
            frictionCombine=base.frictionCombine, restitutionCombine=base.restitutionCombine)

    def _coefficients(self, material: Any) -> Material:
        """The coefficients of ``material``: a defined or preset name, a Material, or None for the default."""
        if isinstance(material, str):
            return self.materials.get(material).material
        return Material.coerce(material)

    def _proxy(self, node: Any, proxy: Any, kind: str) -> Proxy:
        dynamic = kind in ('dynamic', 'kinematic')
        if isinstance(proxy, Proxy):
            return proxy
        if proxy is None:
            return Proxy.from_node(node, 'auto', dynamic)
        if isinstance(proxy, str):
            return Proxy.from_node(node, proxy, dynamic)
        return Proxy.from_node(proxy, 'auto', dynamic)

    def scenery_changed(self, root: Any, generation: Any) -> int:
        """Make static bodies of the shapes ``root`` holds that no body claims.

        The render pass calls this each frame with the scene and a number that
        changes when the scene's paths do; nothing is looked at while the number
        is the same. Returns how many shapes were new. The shapes' triangles are
        cooked off this thread and each body joins the world when its cooking is done.
        """
        return self.scenery.update(root, generation)

    def _derive(self, node: Any) -> Body:
        """A static body for scenery ``node``, waiting for its triangles to be cooked."""
        uid = next(self._uids)
        body = Body(self, uid, 'static', node, None, _ZERO3, (0.0, 0.0, 1.0, 0.0), 0.0)
        body.derived = True
        self._bodies[uid] = body
        self._by_node[node] = body
        return body

    def _cook_later(self, body: Body, make_spec: Callable[[], BodySpec | None]) -> None:
        """Run ``make_spec`` on the cooking thread; :meth:`frame` adds the body when it is done."""
        body._pending = True
        if self._cooker is None:
            self._cooker = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix='physics-cook')
        self._outstanding += 1

        def job() -> None:
            try:
                spec = make_spec()
            except Exception:
                log.exception('could not cook the collider of %r', body.node)
                spec = None
            self._cooked_results.put((body, spec))

        self._cooker.submit(job)

    @property
    def cooking(self) -> int:
        """How many scenery colliders are still being cooked."""
        return self._outstanding

    def wait_cooked(self, timeout: float = 10.0) -> bool:
        """Wait until the cooking in progress is done and its bodies are in the world.

        Returns False if it is not done in ``timeout`` seconds.
        """
        deadline = time.monotonic() + timeout
        while True:
            self._pump_cooked()
            if self._outstanding == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.002)

    #: The seconds a world held inline waits for its scenery's cooking before a step.
    COOK_WAIT = 60.0

    def _wait_for_scenery(self) -> None:
        """Wait for the scenery being cooked, so it joins a world held inline before the next step.

        The step a collider first takes part in is then the same on every run,
        however fast the cooking thread is.
        """
        if not self.wait_cooked(self.COOK_WAIT):
            log.warning('scenery still cooking after %.0f s; the world steps without it',
                        self.COOK_WAIT)

    def _pump_cooked(self) -> None:
        while True:
            try:
                body, spec = self._cooked_results.get_nowait()
            except queue.Empty:
                return
            self._outstanding -= 1
            self.cooked += 1
            body._pending = False
            deferred, body._deferred = body._deferred, []
            if not body.alive:
                continue
            if spec is None:
                self.remove(body)
                continue
            body.proxy = spec.proxy
            if not self._closed:
                self._send(Command('add', body.uid, (spec,), next(self._seq)))
                for op, args in deferred:
                    seq = next(self._seq)
                    self._send(Command(op, body.uid, args, seq))
                    if op == 'place' and body._placed is not None:
                        body._placed = (seq, *body._placed[1:])

    def add_ground(self, ground: Any, extent: Any = None, height_range: Any = None,
                   feature: float = 1.0, **options: Any) -> Body:
        """Make a static body of land that answers a height at each ``(x, z)``.

        ``ground`` is any object with ``sample(x, z)``, as a
        :class:`~OpenGLContext.scenegraph.vegetation.grid.Ground` has, so the
        surface a body meets is the one the terrain node draws. A ground that also
        has ``normal(x, z)``, an ``(..., 3)`` array of unit normals, is asked for
        its normals where the height's slope would cost several samples. ``extent`` is
        ``((x_min, z_min), (x_max, z_max))`` or None for land without an edge;
        ``height_range`` is ``(lowest, highest)`` and is found by sampling a
        grid of the extent (or 1000 metres about the origin) when it is not given.
        ``feature`` is the horizontal distance over which the land changes
        appreciably. Options are the material options of :meth:`add_static`.
        """
        low, high = height_range if height_range is not None else _sampled_heights(ground, extent)
        proxy = Proxy.heightfield(sample=ground.sample, normal=getattr(ground, 'normal', None),
                                  vectorized=True, extent=extent,
                                  height_range=(float(low), float(high)), feature=float(feature))
        return self._add_object('static', ground, proxy, options)

    def _add_object(self, kind: str, key: Any, proxy: Proxy, options: dict[str, Any]) -> Body:
        """A body for something that is not a scenegraph node, found by ``key``."""
        unknown = set(options) - self._OPTIONS
        if unknown:
            raise TypeError('unknown option %s' % ', '.join(sorted(unknown)))
        named = options.get('material')
        body = self._add_placed(kind, proxy, (0.0, 0.0, 0.0), None, self._material(options),
                                self.filters.index(options.get('collision_filter')),
                                named if isinstance(named, str) else None)
        self._by_node[key] = body
        return body

    def _add_placed(self, kind: str, proxy: Proxy, position: Any, orientation: Any = None,
                    material: Any = None, collision_filter: int = -1,
                    named: str | None = None) -> Body:
        """A static body with no node, standing at ``position`` turned by the quaternion ``orientation``.

        ``named`` is the name of its material, which says what a strike on it sounds like.
        """
        uid = next(self._uids)
        quaternion = (0.0, 0.0, 0.0, 1.0) if orientation is None else tuple(
            float(v) for v in orientation)
        place = tuple(float(v) for v in position)
        sounding = self.materials.sound_of(named) is not None
        spec = BodySpec(uid, kind, proxy, Motion(), place, quaternion,
                        material, collision_filter, report=sounding)
        body = Body(self, uid, kind, None, proxy, np.asarray(place), quat_to_vrml_rotation(quaternion),
                    0.0)
        body.material = named
        body._surface = self._coefficients(material)
        if sounding:
            self._send_world('logging', True)
        self._bodies[uid] = body
        if not self._closed:
            self._send(Command('add', uid, (spec,), next(self._seq)))
        return body

    def add_collider_source(self, source: Any, focus: Callable[[], Any] | None = None) -> SourceHandle:
        """Have ``source`` make colliders as ``focus`` nears them and drop them as it leaves.

        ``source.update(focus)`` returns a
        :class:`~OpenGLContext.physics.sources.Changes`; it is called once a
        frame with the position of the focus, which is what the callable
        ``focus`` returns (the first character's feet where it is left out).
        """
        if focus is None:
            if not self._characters:
                raise ValueError('a collider source needs a focus: pass focus=, or add a character first')
            watched = self._characters[0]

            def focus() -> Any:
                return watched.position

        handle = SourceHandle(self, source, focus)
        self._sources.append(handle)
        return handle

    def add_static_instances(self, proxy: Proxy, positions: Any, **options: Any) -> StaticInstances:
        """Make a static body at each row of ``positions`` (an ``(n, 3)`` array), all of one shape.

        For trunks, posts and rocks: the world holds the shape once and the
        bodies in bulk. The bodies have no handles; the returned set removes
        them together.
        """
        points = np.asarray(positions, dtype='d')
        if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
            raise ValueError('positions are an (n, 3) array with at least one row, not shape %r'
                             % (points.shape,))
        first = next(self._uids)
        for _ in range(len(points) - 1):
            next(self._uids)
        batch = BodyBatch(first, proxy, points, self._material(options),
                          self.filters.index(options.get('collision_filter')))
        if not self._closed:
            self._send(Command('add_many', 0, (batch,), next(self._seq)))
        return StaticInstances(self, first, len(points))

    def add_gravity_zone(self, region: Any, gravity: Any = 9.81, toward: Any = None,
                         priority: int = 0, replace: bool = False, stop: bool = False) -> GravityZone:
        """Change gravity inside ``region``, a :class:`~OpenGLContext.physics.zones.Box` or ``Sphere``.

        ``gravity`` is an acceleration vector in metres a second squared, or a
        magnitude pointing down, or toward ``toward``, a point, where that is
        given. A higher ``priority`` wins; ``replace`` drops the lower ones
        instead of adding to them, and ``stop`` ends the counting at this zone.
        """
        values = np.atleast_1d(np.asarray(gravity, dtype='d'))
        strength, direction = float(values[0]), (0.0, -1.0, 0.0)
        if toward is None and values.size == 3:
            strength = float(np.linalg.norm(values))
            if strength > 0.0:
                direction = (float(values[0] / strength), float(values[1] / strength),
                             float(values[2] / strength))
        point = None if toward is None else vector(toward, 'toward')
        zone = GravityZone(region, strength, direction, point, int(priority),
                           bool(replace), bool(stop), uid=next(self._zone_ids))
        self._send_world('gravity_zone', zone)
        return zone

    def zones_changed(self, placed: Any) -> bool:
        """Bring the world's zone gravity to the scene's zones, as the render pass places them.

        Returns whether they were other placements than last time.
        """
        from OpenGLContext.physics.zones import ZoneRegion, gravity_zones  # noqa: PLC0415 imports the scenegraph
        from OpenGLContext.scenegraph.zone import GRAVITY  # noqa: PLC0415 imports the scenegraph

        carrying = tuple(zone for zone in placed if zone.setting(GRAVITY) is not None)
        if len(carrying) == len(self._zones_placed) and all(
                one is other for one, other in zip(carrying, self._zones_placed, strict=True)):
            return False
        self._zones_placed = carrying
        self._send_world('gravity_zones', ZoneRegion, gravity_zones(carrying))
        return True

    def show_proxies(self, on: bool = True) -> None:
        """Draw the box and sphere bodies as wireframes where they are, to see what the world
        collides with; False takes the drawing out."""
        if on and self._overlay is None and self._mount is not None:
            from OpenGLContext.physics.debugdraw import ProxyOverlay  # noqa: PLC0415 imports the scenegraph

            if self._engine.stand_ins:
                self._bring_up_all()
            self._overlay = ProxyOverlay(self)
            self._overlay.update()
            self._mount(self._overlay.root, True)
        elif not on and self._overlay is not None:
            if self._mount is not None:
                self._mount(self._overlay.root, False)
            self._overlay = None

    def add_character(self, node: Any = None, capabilities: Any = None,
                      position: Any = (0.0, 0.0, 0.0), gravity: float | None = None, *,
                      model: Any = None, animations: Any = None, parent: Any = None,
                      fit: bool = True, facing: bool = True,
                      pass_group: str | None = None) -> Character:
        """Make a walker standing with its feet at ``position``.

        ``capabilities`` is a :class:`~OpenGLContext.physics.types.CharacterCapabilities`
        (speeds, jump height, capsule size, mass). The character is stepped in
        :meth:`frame`.

        ``node``, where given, is placed at the feet each frame. ``model`` is a
        :class:`~OpenGLContext.character.model.CharacterModel`, a loaded glTF scene, the
        bytes of a ``.glb``, or a path or URL; the character wears it in a node
        it makes, appended to ``parent`` where that is given, scaled to the
        capsule's height unless ``fit`` is false, and turned toward where the
        character goes unless ``facing`` is false. The model's shapes are not
        scenery: the world collides with the capsule alone. ``animations`` is a
        :class:`~OpenGLContext.character.locomotion.ClipMap`, ``'ual'`` for the
        Universal Animation Library's names or ``'guess'`` to match the model's
        clip names to the roles; the model then plays them for what the
        character is doing. Characters given the same ``pass_group`` name walk
        through one another (:attr:`Character.pass_group`).
        """
        caps = CharacterCapabilities.coerce(capabilities)
        pull = float(np.linalg.norm(self._gravity)) if gravity is None else float(gravity)
        wearing = _model_of(model)
        clip_map = _clip_map_of(animations, wearing)
        turn = None
        if wearing is not None:
            from OpenGLContext.scenegraph.transform import Transform  # noqa: PLC0415 imports the scenegraph

            if fit:
                self._fit_model(wearing, caps)
            _not_scenery(wearing.group)
            turn = Transform(children=[wearing.group])
            if node is None:
                node = Transform(translation=tuple(float(v) for v in position), children=[turn])
            else:
                node.children = [*node.children, turn]
            if parent is not None:
                parent.children.append(node)
        from OpenGLContext.character.facing import Facing  # noqa: PLC0415 only a character with a body needs it

        self._bring_up_all()
        made = Character(self, node, caps, position, pull, model=wearing, clip_map=clip_map,
                         facing=Facing() if facing and wearing is not None else None,
                         turn_node=turn)
        self._characters.append(made)
        made.pass_group = pass_group
        return made

    @staticmethod
    def _fit_model(model: Any, capabilities: Any) -> None:
        """Scale ``model`` to the capsule's standing height, its lowest point at the feet."""
        from OpenGLContext.character.facing import fit_to_height, model_bounds  # noqa: PLC0415 only a character with a body needs it

        bounds = model_bounds(model)
        if bounds is not None:
            fit_to_height(bounds[0], bounds[1], float(capabilities.standHeight)).place(model.group)

    @property
    def characters(self) -> tuple[Character, ...]:
        """The characters in the world, in the order they were added."""
        return tuple(self._characters)

    def _character_replica(self) -> Any:
        """The render thread's copy of the bodies, made on first use; characters step against it."""
        if self._replica is None:
            self._replica = self._engine.build_replica(self._specs, self._snapshot)
        return self._replica

    def _register_body(self, kind: str, proxy: Proxy, centre: Any) -> Body:
        """A body of ``kind`` with no node the engine made itself, such as a character's capsule."""
        uid = next(self._uids)
        body = Body(self, uid, kind, None, proxy, np.asarray(centre, dtype='d'),
                    (0.0, 0.0, 1.0, 0.0), 0.0)
        self._bodies[uid] = body
        return body

    def _add_standin(self, centre: Any, capabilities: Any, reach: float) -> Body:
        """The kinematic body the world sees for a character, with no node."""
        proxy = stand_in_proxy(capabilities, reach)
        uid = next(self._uids)
        spec = BodySpec(uid, 'kinematic', proxy, Motion(),
                        tuple(float(v) for v in centre), (0.0, 0.0, 0.0, 1.0), report=True)
        body = Body(self, uid, 'kinematic', None, proxy, np.asarray(centre, dtype='d'),
                    (0.0, 0.0, 1.0, 0.0), 0.0)
        self._bodies[uid] = body
        self._movers.append(body)
        if not self._closed:
            self._send(Command('add', uid, (spec,), next(self._seq)))
            self._ensure_started()
        return body

    def log_handler_failure(self, function: Callable[..., Any], argument: Any) -> None:
        """Log that a handler raised, once for each function."""
        log.exception('physics handler %r failed on %r', function, argument)

    def cook(self, node: Any, strategy: str = 'auto', dynamic: bool = True) -> Proxy:
        """A :class:`Proxy` cooked from what ``node`` draws, to share between bodies."""
        return Proxy.from_node(node, strategy, dynamic)

    def set_contact_filter(self, function: Callable[[Approach], Any] | None) -> None:
        """Ask ``function(approach)`` about each pair as it first touches; None asks nothing.

        ``approach`` is an :class:`~OpenGLContext.physics.filters.Approach`: the
        two bodies, how fast and how hard they meet, where and along what
        normal. True or None solves the pair; False lets the two pass through
        each other until they part, as a pane that breaks under the blow lets
        the ball through. Only pairs with a body that has a handler are asked.
        It runs on the thread that steps the world, so it reads bodies and
        does not change the scene.
        """
        if not self._closed:
            self._engine.set_contact_filter(function)

    # -- joints (OpenGLContext.physics.joints) ----------------------------
    def add_hinge(self, body: Any, to: Any = None, *, anchor: Any, axis: Any,
                  limits: Any = None, motor: Any = None, collide: bool = False) -> Joint:
        """Hold ``body`` to ``to`` (a body or node; None for the world) so it turns about ``axis`` through ``anchor``.

        ``anchor`` and ``axis`` are world coordinates as the bodies stand now.
        ``limits`` is ``(lower, upper)`` in radians from the angle it starts at;
        ``motor`` is ``(speed, torque)`` in radians a second and newton-metres.
        """
        return make_joint(self, 'hinge', body, to, anchor=anchor, axis=axis, limits=limits,
                          motor=motor, collide=collide)

    def add_ball(self, body: Any, to: Any = None, *, anchor: Any,
                 collide: bool = False) -> Joint:
        """Hold ``body`` to ``to`` at the world point ``anchor``, about which both turn freely."""
        return make_joint(self, 'ball', body, to, anchor=anchor, collide=collide)

    def add_slider(self, body: Any, to: Any = None, *, axis: Any, limits: Any = None,
                   motor: Any = None, collide: bool = False) -> Joint:
        """Let ``body`` slide against ``to`` along ``axis`` only, neither turning against the other.

        ``limits`` is ``(lower, upper)`` in metres from where it starts;
        ``motor`` is ``(speed, force)`` in metres a second and newtons.
        """
        return make_joint(self, 'slider', body, to, axis=axis, limits=limits, motor=motor,
                          collide=collide)

    def add_distance(self, body: Any, to: Any = None, *, anchor: Any = None,
                     to_anchor: Any = None, length: float | None = None,
                     collide: bool = False) -> Joint:
        """Keep the world point ``anchor`` on ``body`` at ``length`` metres from ``to_anchor`` on ``to``.

        The anchors default to the bodies' centres; the world needs its
        ``to_anchor``. ``length`` defaults to the distance between them now.
        """
        return make_joint(self, 'distance', body, to, anchor=anchor, to_anchor=to_anchor,
                          length=length, collide=collide)

    def add_universal(self, body: Any, to: Any = None, *, anchor: Any, axis: Any, to_axis: Any,
                      collide: bool = False) -> Joint:
        """Hold ``body`` to ``to`` at ``anchor`` so a spin about ``axis`` on ``body`` turns ``to_axis`` on ``to``.

        A universal (cardan) joint: ``axis`` turns with ``body`` and
        ``to_axis`` with ``to`` (the world where ``to`` is None), and the two
        keep the angle between them they start at. Each body turns freely
        about its own axis. The axes are world directions as the bodies stand
        now and must not lie along one line.
        """
        return make_joint(self, 'universal', body, to, anchor=anchor, axis=axis, to_axis=to_axis,
                          collide=collide)

    def add_wheel(self, body: Any, to: Any = None, *, anchor: Any, steering_axis: Any, axle: Any,
                  steering_limits: Any = None, motor: Any = None, steering_motor: Any = None,
                  suspension: Any = None, collide: bool = False) -> Joint:
        """Hold wheel ``body`` to ``to`` so it spins about ``axle`` and steers about ``steering_axis``.

        ``steering_axis`` is carried by ``to`` and ``axle`` by the wheel; both
        are world directions as the bodies stand now. ``steering_limits`` is
        ``(lower, upper)`` in radians; equal limits lock the steering.
        ``motor`` is ``(speed, torque)`` for the axle and ``steering_motor``
        for the steering, in radians a second and newton-metres.
        ``suspension`` is ``(stiffness, damping)`` in newtons a metre and
        newton-seconds a metre, a spring along the steering axis; without it
        the anchor is held. :attr:`Joint.angles` reads the steering and the spin.
        """
        return make_joint(self, 'wheel', body, to, anchor=anchor, axis=steering_axis,
                          to_axis=axle, limits=steering_limits, motor=motor,
                          steering_motor=steering_motor, suspension=suspension, collide=collide)

    def add_motor(self, body: Any, to: Any = None, *, axes: Any, torques: Any,
                  collide: bool = True) -> Joint:
        """Turn ``body`` against ``to`` about up to three ``axes`` with ``torques``, every step.

        ``axes`` are world directions as the bodies stand now, carried by ``to``
        (the world where ``to`` is None); ``torques`` are newton-metres, one for
        each axis, turning ``body`` forward and ``to`` back. The joint holds
        nothing else, so the two collide unless ``collide`` is false.
        :meth:`Joint.drive` with ``torques=`` changes them.
        """
        return make_joint(self, 'motor', body, to, axes=axes, torques=torques, collide=collide)

    def remove(self, body: Body) -> None:
        """Take ``body`` out of the world, with its joints. Removing twice is harmless.

        From a physics callback the world drops the body at once and the
        service's own tables let go of it in the next :meth:`frame`.
        """
        if not body.alive:
            return
        body.alive = False
        on_worker = self._engine.on_engine_thread()
        if on_worker:
            self.render.call(self._unpass, body.uid)
        else:
            self._unpass(body.uid)
        seq = 0
        if not self._closed:
            seq = next(self._seq)
            self._send(Command('remove', body.uid, (), seq))
        if on_worker:
            self.render.call(self._forget, body, seq)
        else:
            self._forget(body, seq)

    def _unpass(self, uid: int) -> None:
        """Have the characters' controllers stop walking through body ``uid``'s slot,
        before the slot is freed for another body."""
        if uid in self._passable:
            replica = self._replica
            if not self._engine.stand_ins:
                for character in self._characters:
                    character._controller.ignore.discard(uid)
            elif replica is not None and uid in replica:
                for character in self._characters:
                    character._controller.ignore.discard(replica.index_of(uid))
            self._passable.discard(uid)

    def _forget(self, body: Body, seq: int) -> None:
        """Let go of removed ``body`` in the render thread's tables; ``seq`` is its removal's
        sequence, after which its handlers end, or 0 to end them now."""
        if seq:
            self._gone.append((seq, body.uid))
        else:
            self.handlers.forget_body(body.uid)
        if body.derived:
            self.scenery.release(body.node)
        self._bodies.pop(body.uid, None)
        if body.node is not None and self._by_node.get(body.node) is body:
            del self._by_node[body.node]
        if body in self._movers:
            self._movers.remove(body)
            row = None if self._posed_rows is None else self._posed_rows.get(body.uid)
            if row is not None:
                self._pose_rows[row] = None
        self._retired[body.uid] = body
        while len(self._retired) > RETIRED_KEPT:
            self._retired.popitem(last=False)

    def body_for(self, node: Any, within: Any = None) -> Body | None:
        """The body of ``node``, or None.

        A node with no body of its own answers with the one body under it, when
        there is exactly one: the scenery body of the shape a glTF node holds.
        With ``within``, a node under it, the nearest ancestor on the way down
        that has a body answers for a node that has none.
        """
        found = self._by_node.get(node)
        if found is not None:
            return found
        if within is not None:
            path = _path_to(within, node)
            for ancestor in reversed(path or ()):
                found = self._by_node.get(ancestor)
                if found is not None:
                    return found
        below = self.bodies_in(node)
        return below[0] if len(below) == 1 else None

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
        if not body.alive or self._closed:
            return 0
        if body._pending:
            body._deferred.append((op, args))
            return 0
        seq = next(self._seq)
        self._send(Command(op, body.uid, args, seq))
        return seq

    def _send(self, command: Command) -> None:
        """Send ``command`` to the worker and keep the specs and the replica in step.

        The specs and the replica belong to the render thread: a command made
        on the worker thread is applied to the world at once and to them in
        the next :meth:`frame`.
        """
        if self._engine.on_engine_thread():
            self._engine.submit(command)
            self.render.call(self._record, command)
            return
        try:
            self._record(command)
        finally:
            self._engine.submit(command)

    def _record(self, command: Command) -> None:
        """Bring the specs, and the replica where there is one, to what ``command`` makes of the world."""
        if command.op == 'add':
            self._specs[command.uid] = command.args[0]
        elif command.op == 'add_many':
            self._specs[command.args[0].first] = command.args[0]
        elif command.op == 'remove':
            self._specs.pop(command.uid, None)
        elif command.op == 'place' and isinstance(self._specs.get(command.uid), BodySpec):
            self._specs[command.uid] = self._respec_placed(self._specs[command.uid], *command.args)
        elif command.op == 'remove_many':
            self._specs.pop(command.args[0], None)
        elif command.op in ('mass', 'body_material') and isinstance(
                self._specs.get(command.uid), BodySpec):
            spec = self._specs[command.uid]
            self._specs[command.uid] = (
                dataclasses.replace(spec, motion=dataclasses.replace(spec.motion,
                                                                     mass=command.args[0]))
                if command.op == 'mass' else dataclasses.replace(spec, material=command.args[0]))
        if self._replica is not None:
            self._replica.apply(command)

    @staticmethod
    def _respec_placed(spec: BodySpec, translation: Any, axis_angle: Any) -> BodySpec:
        """``spec`` with the pose a 'place' command gives, so a replica made later starts there."""
        position = spec.position if translation is None else tuple(translation)
        orientation = spec.orientation if axis_angle is None else tuple(
            vrml_rotation_to_quat(np.asarray(axis_angle, dtype='d')))
        return dataclasses.replace(spec, position=position, orientation=orientation)

    def _send_world(self, op: str, *args: Any) -> None:
        if not self._closed:
            self._send(Command(op, 0, args, next(self._seq)))

    def _run(self, function: Callable[[Any], Any]) -> concurrent.futures.Future[Any]:
        """Call ``function(world)`` on the worker; the future holds its answer.

        A world with no thread running is reached on the calling thread, at
        once. Each character's stand-in is written first.
        """
        self._bring_up_all()
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._send_world('run', function, future)
        self._engine.flush()
        return future

    def post(self, function: Callable[..., Any], *arguments: Any) -> None:
        """Call ``function(*arguments)`` on the stepping thread before the next step; returns None.

        What it does to bodies through their handles takes effect at once, as
        in an :meth:`on_step` function.
        """
        self._send_world('post', function, arguments)

    def flush(self) -> None:
        """Apply the commands waiting for the world now, without stepping it.

        An inline or standalone service applies a write at the start of its next
        step; code that reads the world between steps calls this first to see
        the writes it has just made. A service whose thread is running applies
        them on that thread, and this leaves them there. A Jolt world applies
        commands only at the start of a tick, so this does nothing there.
        """
        self._engine.flush()

    def drop_remainder(self) -> None:
        """Forget the time carried over toward the next step.

        An inline or standalone service steps whole ticks and carries what is
        left of a frame to the next; a game that starts something afresh calls
        this so the leftover is not simulated into it. The characters' part
        step is forgotten with it.
        """
        self._send_world('drop_remainder')
        self._character_clock.drop()

    # -- the frame ----------------------------------------------------------
    def step(self, dt: float) -> None:
        """Advance the world by ``dt`` seconds by hand, for a service nothing else steps."""
        self._engine.step(dt)

    def frame(self, dt: float) -> bool:
        """Do the render thread's share of one frame; True if the scene changed or is still moving.

        Takes what the worker has published, writes poses onto the nodes of
        bodies that move, delivers events to render-thread handlers and applies
        the scene changes handlers queued from the worker. An inline worker
        steps ``dt`` seconds first.

        Each framed character takes one step of the world's fixed length for
        each fixed step the frame owes, with its latest moves, so a character
        takes the same steps as the world. Inline, that is the count the
        world's clock gives; with the world on its own thread, the service
        counts the steps at the same rate on the render thread.
        """
        if not self._enabled or self._closed:
            if not self._closed:
                self._pump_cooked()
            self.render.apply()
            return False
        if self._pinned and self._outstanding:
            self._wait_for_scenery()
        self._pump_cooked()
        self._raise_worker_error()
        out = self._engine.collect(dt)
        for character in self._characters:
            character._fresh = False
        if out.snapshot is not None:
            self._snapshot = out.snapshot
            if self._replica is not None:
                self._replica.sync(out.snapshot)
            self._write_poses(out.snapshot)
            if self._overlay is not None:
                self._overlay.update()
            moving = out.snapshot.awake & (out.snapshot.dynamic | (
                np.abs(out.snapshot.linear_velocity).sum(axis=1) > 0.0))
            self._awake = bool(moving.any())
        for handle in list(self._sources):
            self._guarded(handle, handle.update)
        walking = False
        steps, alpha = self._character_steps(dt)
        step = self._engine.step_dt
        for character in list(self._characters):
            if character.framed:
                self._guarded(character, character._frame, steps, step, dt, alpha)
                walking = walking or character.busy
        if out.events:
            self._dispatch(out.events)
        self._finish_removals()
        applied = self.render.apply()
        return bool(self._awake or applied or walking)

    def _character_steps(self, dt: float) -> tuple[int, float]:
        """The fixed steps the characters owe this frame, and how far through the next one it ends."""
        engine = self._engine
        if engine.mode == 'inline' or not engine.stand_ins:
            return engine.character_steps(dt)
        clock = self._character_clock
        clock.step, clock.longest = engine.step_dt, engine.max_catch_up
        return clock.owed(dt), clock.alpha

    def _guarded(self, owner: Any, function: Callable[..., Any], *arguments: Any) -> None:
        """Call ``function(*arguments)`` for ``owner``, a source or a character, in the frame.

        An exception is logged with its traceback, once for each distinct
        failure of each owner, and the frame goes on to the next.
        """
        try:
            function(*arguments)
        except Exception as error:  # noqa: BLE001 one owner's failure leaves the others framed
            signature = (type(error), str(error))
            if self._failures.get(owner) != signature:
                self._failures[owner] = signature
                log.exception('%r failed in the physics frame', owner)

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

    def _write_poses(self, snapshot: Snapshot) -> bool:
        """Write the pose of each body whose row ``snapshot`` lists as changed onto its node.

        A body placed by a command the snapshot does not include yet keeps the
        pose it was placed at, and is looked at again in the next frame.
        """
        table = self._pose_table(snapshot.rows)
        changed = snapshot.changed_since(self._posed_version)
        self._posed_version = snapshot.version
        rows: Iterable[int] = range(len(table)) if changed is None else changed.tolist()
        held, self._held = self._held, []
        if held:
            rows = sorted(set(rows).union(held))
        applied = snapshot.applied_seq
        nodes, written = [], []
        for row in rows:
            body = table[row]
            if body is None:
                continue
            placed = body._placed
            if placed is not None:
                if applied < placed[0]:
                    self._held.append(row)
                    continue
                body._placed = None
            if body.node is None:
                continue
            nodes.append(body.node)
            written.append(row)
        if not nodes:
            return False
        take = np.asarray(written, dtype=np.intp)
        write_poses(nodes, snapshot.position[take], snapshot.axis_angle[take])
        return True

    def _pose_table(self, rows: dict[int, int]) -> list[Body | None]:
        """The body at each row of a snapshot with row table ``rows``; None for a row of no body here."""
        if self._posed_rows is not rows:
            table: list[Body | None] = [None] * len(rows)
            for body in self._movers:
                row = rows.get(body.uid)
                if row is not None:
                    table[row] = body
            self._pose_rows, self._posed_rows = table, rows
            self._posed_version = None
            self._held = []
        return self._pose_rows

    # -- reading ----------------------------------------------------------
    def poses(self, bodies: Iterable[Body | int], interpolated: bool = True) -> Poses:
        """The poses, velocities and masses of ``bodies`` (handles or uids), a row each in that order.

        Read on the render thread, a body that moves is where the frame draws
        it, part of the way into the next step; ``interpolated=False`` gives
        where the last step left it. Read on the stepping thread, in an
        :meth:`on_step` function, the world answers as it stands. Raises
        KeyError for a uid the service does not hold.
        """
        found = [self._held_body(one) for one in bodies]
        if not found:
            return Poses.empty()
        count = len(found)
        position, orientation = np.empty((count, 3)), np.empty((count, 4))
        velocity, spin = np.empty((count, 3)), np.empty((count, 3))
        asleep = np.zeros(count, dtype=bool)
        rest = self._gather(found, interpolated, position, orientation, velocity, spin, asleep)
        for row in rest:
            state = self._state(found[row], interpolated)
            position[row] = state.position
            orientation[row] = vrml_rotation_to_quat(np.asarray(state.axis_angle, dtype='d'))
            velocity[row], spin[row] = state.velocity, state.angular_velocity
            asleep[row] = state.asleep
        return Poses(np.array([body.uid for body in found], dtype='i8'), position, orientation,
                     velocity, spin, np.array([body.mass for body in found], dtype='d'), asleep)

    def _held_body(self, given: Body | int) -> Body:
        if isinstance(given, Body):
            return given
        found = self._body_of(int(given))
        if found is None:
            raise KeyError('no body has uid %r in this service' % (given,))
        return found

    def _gather(self, bodies: Sequence[Body], interpolated: bool, position: np.ndarray,
                orientation: np.ndarray, velocity: np.ndarray, spin: np.ndarray,
                asleep: np.ndarray) -> list[int]:
        """Fill the rows of ``bodies`` the world or the snapshot lists, in bulk; the rows left to fill.

        A body placed by a write the world has not applied yet is left, so its
        row is read as :attr:`Body.position` reads it.
        """
        snapshot = self._snapshot
        rest = []
        if self._engine.on_engine_thread():
            found = self._engine.live_poses([body.uid for body in bodies])
            for row, body in enumerate(bodies):
                live = found.get(body.uid)
                if live is None:
                    rest.append(row)
                    continue
                position[row], orientation[row] = live.position, live.orientation
                velocity[row], spin[row] = live.velocity, live.angular_velocity
                asleep[row] = live.asleep
            return rest
        table: dict[int, int] = {} if snapshot is None else snapshot.rows
        rows, wanted = [], []
        for row, body in enumerate(bodies):
            at = table.get(body.uid)
            if at is None or body._placed is not None:
                rest.append(row)
            else:
                rows.append(row)
                wanted.append(at)
        if rows:
            take = np.asarray(wanted, dtype='i8')
            assert snapshot is not None
            places = (snapshot.step_position if not interpolated
                      and snapshot.step_position is not None else snapshot.position)
            turns = (snapshot.step_orientation if not interpolated
                     and snapshot.step_orientation is not None else snapshot.orientation)
            position[rows] = places[take]
            orientation[rows] = turns[take]
            velocity[rows] = snapshot.linear_velocity[take]
            spin[rows] = snapshot.angular_velocity[take]
            asleep[rows] = ~snapshot.awake[take] & snapshot.dynamic[take]
        return rest

    def _state(self, body: Body, interpolated: bool = True) -> _State:
        state = (self._live_state(body) if self._engine.on_engine_thread()
                 else self._published_state(body, interpolated))
        placed = body._placed
        if placed is not None and (placed[0] == 0 or self._snapshot is None
                                   or self._snapshot.applied_seq < placed[0]):
            position = state.position if placed[1] is None else placed[1]
            axis_angle = state.axis_angle if placed[2] is None else placed[2]
            return _State(position, axis_angle, state.velocity, state.angular_velocity,
                          state.asleep)
        return state

    def _live_state(self, body: Body) -> _State:
        live = self._engine.live_poses([body.uid]).get(body.uid)
        if live is None:
            return self._published_state(body)
        axis_angle = quat_to_vrml_rotation(live.orientation)
        return _State(live.position, np.asarray(axis_angle, dtype='d'), live.velocity,
                      live.angular_velocity, live.asleep)

    def _published_state(self, body: Body, interpolated: bool = True) -> _State:
        snapshot = self._snapshot
        row = None if snapshot is None else snapshot.rows.get(body.uid)
        if snapshot is None or row is None:
            return _State(body._position, body._axis_angle, _ZERO3, _ZERO3, False)
        position, axis_angle = snapshot.position[row], snapshot.axis_angle[row]
        if not interpolated and snapshot.step_position is not None:
            position = snapshot.step_position[row]
            assert snapshot.step_orientation is not None
            axis_angle = np.asarray(quat_to_vrml_rotation(snapshot.step_orientation[row]),
                                    dtype='d')
        return _State(position, axis_angle,
                      snapshot.linear_velocity[row], snapshot.angular_velocity[row],
                      not bool(snapshot.awake[row]) and bool(snapshot.dynamic[row]))

    def _joint_reading(self, joint: Joint) -> tuple[float, ...]:
        """``joint``'s readings: live inline and on the stepping thread, else the last published."""
        return self._engine.joint_reading(joint, self._snapshot)


    # -- state ------------------------------------------------------------
    def save_state(self) -> bytes:
        """The bodies' and joints' state as bytes, read between steps, for :meth:`restore_state`.

        Characters, the step count and commands still waiting are not part of
        it. Raises NotImplementedError on an engine that keeps no such state
        (omi_physics).
        """
        return self._engine.save_state()

    def restore_state(self, data: bytes) -> None:
        """Put the bodies and joints back as :meth:`save_state` found them, from the next step.

        The world must hold the bodies it held when the state was saved; one
        that does not keeps its own state.
        """
        self._engine.restore_state(data)

    # -- tick-exact code ----------------------------------------------------
    def on_step(self, function: Callable[[StepView], Any]) -> StepHook:
        """Call ``function(view)`` on the stepping thread after every fixed step; returns its hook.

        ``view`` is a :class:`~OpenGLContext.physics.stepview.StepView`: the
        step, :meth:`poses` and the queries as the world stands. Writes made
        through body handles in ``function`` take effect at once. The world
        keeps stepping while a hook is registered; ``hook.cancel()`` removes it.
        A function that raises is logged once and called again at the next step.
        """
        hook = StepHook(function)
        self._step_hooks.append(hook)
        self._ensure_started()
        self._engine.callbacks_changed()
        return hook

    def _run_step_hooks(self, step: Step) -> None:
        if not self._step_hooks:
            return
        view = StepView(self, step)
        for hook in list(self._step_hooks):
            if hook.cancelled:
                self._step_hooks.remove(hook)
                continue
            try:
                hook.function(view)
            except Exception:
                if not hook.failed:
                    hook.failed = True
                    log.exception('physics step hook %r failed', hook.function)

    def _step_hooks_want_steps(self) -> bool:
        return any(not hook.cancelled for hook in self._step_hooks)

    # -- queries ---------------------------------------------------------
    # -- stand-ins that wait ------------------------------------------------
    def _defers_stand_ins(self) -> bool:
        """Whether a character's stand-in is written to the world only when something can see it.

        So for the lone character of an inline service showing no proxies:
        another character's controller reads the stand-ins from the replica,
        which follows each write as it is asked for.
        """
        return (len(self._characters) == 1 and self._engine.stand_ins
                and self._engine.mode == 'inline' and self._enabled and not self._closed and self._overlay is None)

    def _bring_up_all(self) -> None:
        """Make every waiting stand-in write now."""
        for character in self._characters:
            character._bring_up()

    def _settle_stand_ins(self, step: Step) -> None:  # noqa: ARG002 the step is the hook's argument
        """Before a step: write each waiting stand-in that a body in the world can see."""
        for character in self._characters:
            if not character._written:
                character._settle(self._seen_in_step)

    def _stand_ins_want_steps(self) -> bool:
        """Whether a waiting stand-in keeps the world stepping as its write would have: a write
        asked for since the last frame was collected, or a velocity it would have."""
        for character in self._characters:
            if not character._written:
                moving = character._stand_in_at[1] if character._stand_in_at else ()
                if character._fresh or any(moving):
                    return True
        return False

    #: Metres past the box of a body that moves, and past the stand-in's, within which a step
    #: is taken to see the stand-in, beyond what the body can travel in the step.
    SEEN_MARGIN = 0.1
    #: How far past the stand-in, in metres, the fixed triggers and sensors near it are gathered
    #: for the steps that follow, while the layout of the world holds.
    SEEN_GATHER = 4.0

    def _seen_in_step(self, character: Character, due: tuple[float, ...]) -> bool:
        """Whether a dynamic body, a trigger or a sensor of the world can meet ``character``'s
        stand-in in the coming step, at ``due`` or where the world holds it now.

        A fixed trigger or sensor is tested by its box. The box of a body that
        moves is grown by :attr:`SEEN_MARGIN` and by twice what its speed, its
        spin about the far corner of its box and gravity can carry it in a step.
        """
        runtime = self._omi.runtime
        world = runtime.world
        uid = character.body.uid
        if uid not in runtime:
            return True
        index = runtime.entry(uid).index
        fixed, moving = _observers(world)
        across, up = character._stand_in_reach(self.SEEN_MARGIN)
        boxes = [(x - across, y - up, z - across, x + across, y + up, z + across)
                 for x, y, z in (due, world.position[index].tolist())]
        if len(fixed) and self._fixed_seen(character, world, fixed, boxes):
            return True
        moving = moving[moving != index]
        if not len(moving):
            return False
        low, high = world.aabb_min[moving], world.aabb_max[moving]
        dt = runtime.step_dt
        spin = np.linalg.norm(world.angular_velocity[moving], axis=1)
        reach = (np.linalg.norm(world.linear_velocity[moving], axis=1)
                 + spin * np.linalg.norm(high - low, axis=1))
        pull = float(np.linalg.norm(np.asarray(self._gravity, dtype='d')))
        grow = (self.SEEN_MARGIN + 2.0 * dt * reach + pull * dt * dt)[:, None]
        low, high = low - grow, high + grow
        for x0, y0, z0, x1, y1, z1 in boxes:
            if bool(np.any((high[:, 0] >= x0) & (high[:, 1] >= y0) & (high[:, 2] >= z0)
                           & (low[:, 0] <= x1) & (low[:, 1] <= y1) & (low[:, 2] <= z1))):
                return True
        return False

    def _fixed_seen(self, character: Character, world: Any, fixed: np.ndarray,
                    boxes: Sequence[tuple[float, ...]]) -> bool:
        """Whether a fixed trigger or sensor's box meets one of ``boxes``, each
        ``(x0, y0, z0, x1, y1, z1)``.

        The fixed ones within :attr:`SEEN_GATHER` of the boxes are gathered once
        and kept while the boxes stay inside the gathered region and the
        world's layout holds.
        """
        (a, b, c, d, e, f), (g, h, i, j, k, m) = boxes
        lo = (min(a, g), min(b, h), min(c, i))
        hi = (max(d, j), max(e, k), max(f, m))
        key = (world.population_epoch, world.layout_epoch)
        held = self._seen_gathers.get(character.body.uid)
        if (held is None or held[0] != key
                or not (held[1][0] <= lo[0] and held[1][1] <= lo[1] and held[1][2] <= lo[2]
                        and hi[0] <= held[2][0] and hi[1] <= held[2][1] and hi[2] <= held[2][2])):
            gather = self.SEEN_GATHER
            region_lo = tuple(value - gather for value in lo)
            region_hi = tuple(value + gather for value in hi)
            low, high = world.aabb_min[fixed], world.aabb_max[fixed]
            near = (np.all(high >= np.array(region_lo), axis=1)
                    & np.all(low <= np.array(region_hi), axis=1))
            held = (key, region_lo, region_hi,
                    [(*one, *two) for one, two in zip(low[near].tolist(), high[near].tolist(),
                                                      strict=True)])
            self._seen_gathers[character.body.uid] = held
        for x0, y0, z0, x1, y1, z1 in boxes:
            for a0, b0, c0, a1, b1, c1 in held[3]:
                if a1 >= x0 and b1 >= y0 and c1 >= z0 and a0 <= x1 and b0 <= y1 and c0 <= z1:
                    return True
        return False

    def _bring_up_along(self, origins: np.ndarray, directions: np.ndarray, distance: float,
                        radius: float, skip: Any) -> None:
        """Write each waiting stand-in that rays or swept spheres from ``origins`` along
        ``directions`` for ``distance`` can reach."""
        if all(character._written for character in self._characters):
            return
        lengths = np.linalg.norm(directions, axis=1)
        heading = np.divide(directions, lengths[:, None], out=np.zeros_like(directions),
                            where=lengths[:, None] > 0.0)
        ends = origins + heading * max(distance, 0.0)
        self._bring_up_within(np.minimum(origins, ends).min(axis=0) - radius,
                              np.maximum(origins, ends).max(axis=0) + radius, skip)

    def _bring_up_within(self, lo: np.ndarray, hi: np.ndarray, skip: Any) -> None:
        """Write each waiting stand-in, not in ``skip``, whose box meets ``lo`` to ``hi``, at the
        place it is due or where the world holds it."""
        waiting = [character for character in self._characters if not character._written]
        if not waiting:
            return
        skipped = (set() if skip is None else {skip.uid} if isinstance(skip, Body)
                   else {body.uid for body in skip})
        runtime = self._omi.runtime
        for character in waiting:
            uid = character.body.uid
            if uid in skipped:
                continue
            if uid not in runtime:
                character._bring_up()       # added by a command the world has not taken yet
                continue
            held = runtime.world.position[runtime.entry(uid).index]
            for centre in (character._due(), held):
                low, high = character._stand_in_box(centre, self.SEEN_MARGIN)
                if bool(np.all(high >= lo) and np.all(low <= hi)):
                    character._bring_up()
                    break

    @staticmethod
    def _skipped(skip: Any) -> set[int]:
        if skip is None:
            return set()
        bodies = [skip] if isinstance(skip, Body) else list(skip)
        return {body.uid for body in bodies}

    def raycast(self, origin: Any, direction: Any, max_distance: float = 100.0,
                skip: Any = None) -> Hit | None:
        """What a ray from ``origin`` along ``direction`` meets first, or None.

        Answers in the call, from the world as the last tick left it. ``skip``
        is a body, or a list of them, the ray passes through.
        """
        start = np.asarray(origin, dtype='d')
        self._bring_up_along(start[None], np.asarray(direction, dtype='d')[None],
                             float(max_distance), 0.0, skip)
        found = self._engine.raycast(origin, direction, float(max_distance), self._skipped(skip))
        return None if found is None else self._hit(found)

    def raycast_many(self, origins: Any, directions: Any, max_distance: float = 100.0,
                     skip: Any = None) -> list[Hit | None]:
        """Several rays at once, each answered as :meth:`raycast` would answer it."""
        self._bring_up_along(np.asarray(origins, dtype='d').reshape(-1, 3),
                             np.asarray(directions, dtype='d').reshape(-1, 3),
                             float(max_distance), 0.0, skip)
        found = self._engine.raycast_many(origins, directions, float(max_distance),
                                          self._skipped(skip))
        return [None if one is None else self._hit(one) for one in found]

    def line_of_sight(self, start: Any, end: Any, skip: Any = None) -> bool:
        """Whether no body lies between the points ``start`` and ``end``.

        A body past ``end`` does not block the view. ``skip`` is a body, or a list
        of them, the line passes through.
        """
        first = np.asarray(start, dtype='d')
        second = np.asarray(end, dtype='d')
        gap = second - first
        distance = float(np.linalg.norm(gap))
        if distance < 1e-12:
            return True
        return self.raycast(first, gap, distance, skip=skip) is None

    def _hit(self, found: Any) -> Hit:
        uid = found.uid
        return Hit(None if uid is None else self._body_of(uid), np.asarray(found.point),
                   np.asarray(found.normal), float(found.distance), int(found.triangle))

    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: Any = None) -> float | None:
        """How far a sphere of ``radius`` travels along ``direction`` before it touches a body.

        None where it travels ``distance`` clear; 0 where it starts inside a body.
        """
        self._bring_up_along(np.asarray(origin, dtype='d')[None],
                             np.asarray(direction, dtype='d')[None], float(distance),
                             float(radius), skip)
        return self._engine.sweep_sphere(origin, direction, float(distance), float(radius),
                                         self._skipped(skip))

    def overlap(self, proxy: Any, translation: Any, rotation: Any = None,
                skip: Any = None, triggers: bool = False) -> list[Body]:
        """The bodies a shape overlaps when placed at ``translation``, turned by ``rotation``.

        ``proxy`` is a :class:`Proxy`; ``rotation`` is an axis and an angle. The answer lists solid bodies, or
        with ``triggers=True`` the trigger volumes the shape is in.
        """
        if not isinstance(proxy, Proxy):
            raise TypeError('overlap takes a Proxy, not %r' % (proxy,))
        quaternion = (np.array([0.0, 0.0, 0.0, 1.0]) if rotation is None
                      else vrml_rotation_to_quat(rotation))
        if self._engine.stand_ins:
            self._bring_up_within(*self._engine.proxy_bounds(proxy, translation, quaternion), skip)
        found = self._engine.overlap(proxy, translation, quaternion, self._skipped(skip), triggers)
        bodies = [self._body_of(uid) for uid in found]
        return [body for body in bodies if body is not None]

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
        self._engine.callbacks_changed()
        return handler

    def _take_sound(self, body: Body) -> None:
        """Have the world report strikes on ``body`` where its material now has a sound."""
        if self.materials.sound_of(body.material) is not None:
            self._send_world('logging', True)
            self._command('report', body, True)

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
                    self._command('report', self._bodies[uid], True)
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

    def _strike(self, event: PhysicsEvent) -> None:
        """Play the sound of a material where a body of it is struck hard enough."""
        if event.kind != 'contact' or event.phase != 'begin' or event.approach <= SOUND_SPEED:
            return
        for uid in (event.a, event.b):
            body = self._body_of(uid)
            sound = self.materials.sound_of(getattr(body, 'material', None))
            if sound is not None and self._audio is not None:
                self._audio().play(sound, at=tuple(float(v) for v in event.point),
                                   gain=min(1.0, float(event.approach) / SOUND_FULL))
                return

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
        sounds = self._audio is not None and self.materials.has_sounds
        for event in events:
            if sounds:
                self._strike(event)
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
        """The exception that stopped the engine's thread, or None."""
        return self._engine.error

    def _raise_worker_error(self) -> None:
        """Raise a RuntimeError from the exception that stopped the worker, in the first frame after it."""
        error = self._engine.error
        if error is not None and error is not self._raised:
            self._raised = error
            raise RuntimeError('the physics worker stopped: %s' % (error,)) from error

    def close(self) -> None:
        """Stop the worker and let go of the bodies. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self._cooker is not None:
            self._cooker.shutdown(wait=False, cancel_futures=True)
        self._engine.close()


#: The rows of each world's fixed triggers and sensors, and of its dynamic bodies and moving
#: triggers and sensors, by population epoch.
_OBSERVERS: weakref.WeakKeyDictionary[Any, tuple[int, np.ndarray, np.ndarray]] = (
    weakref.WeakKeyDictionary())


def _observers(world: Any) -> tuple[np.ndarray, np.ndarray]:
    """The rows of what can meet a stand-in in ``world``: its fixed triggers and sensors, and its
    dynamic bodies and the triggers and sensors that move."""
    epoch = world.population_epoch
    found = _OBSERVERS.get(world)
    if found is None or found[0] != epoch:
        kind = world.motion_type
        sensing = (world.trigger_shape >= 0) | world.sensor
        found = _OBSERVERS[world] = (epoch, np.flatnonzero(sensing & (kind == 0)),
                                     np.flatnonzero((kind == 2) | (sensing & (kind != 0))))
    return found[1], found[2]


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


class StaticInstances:
    """Static bodies made together by :meth:`Physics.add_static_instances`."""

    def __init__(self, physics: Physics, first: int, count: int) -> None:
        self.physics = physics
        #: How many bodies there are.
        self.count = count
        self._first = first
        self._alive = True

    def remove(self) -> None:
        """Take every body out of the world. Removing twice is harmless."""
        if self._alive:
            self._alive = False
            self.physics._send_world('remove_many', self._first, self.count)
            self.physics._specs.pop(self._first, None)


#: The ``add_*`` options that are numbers, with the bound each must keep.
_NUMBERS = {'mass': 'positive', 'density': 'positive', 'linear_damping': 'non_negative',
            'angular_damping': 'non_negative', 'friction': 'non_negative',
            'restitution': 'non_negative'}


def _checked(options: dict[str, Any]) -> dict[str, Any]:
    """``options`` with each physical value made a finite float or tuple; ValueError naming the
    first that cannot be one."""
    found = dict(options)
    for name, bound in _NUMBERS.items():
        if found.get(name) is not None:
            found[name] = number(found[name], name, **{bound: True})
    if found.get('gravity_factor') is not None:
        found['gravity_factor'] = number(found['gravity_factor'], 'gravity_factor')
    if found.get('translation') is not None:
        found['translation'] = vector(found['translation'], 'translation')
    if found.get('rotation') is not None:
        found['rotation'] = vector(found['rotation'], 'rotation', 4)
    return found


def _not_scenery(group: Any) -> None:
    """Mark each shape under ``group`` as one the world does not collide with.

    A character is its capsule; the model it wears is drawn where the capsule
    is and must not become a static body of its own.
    """
    stack = [group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            node.collide = False
        stack.extend(getattr(node, 'children', None) or ())


def _sampled_heights(ground: Any, extent: Any, margin: float = 0.2) -> tuple[float, float]:
    """The lowest and highest height of ``ground`` over ``extent``, from a grid of samples, widened by ``margin``."""
    (x0, z0), (x1, z1) = extent if extent is not None else ((-500.0, -500.0), (500.0, 500.0))
    xs, zs = np.meshgrid(np.linspace(x0, x1, 65), np.linspace(z0, z1, 65))
    heights = np.asarray(ground.sample(xs, zs), dtype='d')
    low, high = float(heights.min()), float(heights.max())
    pad = max(high - low, 1.0) * margin
    return low - pad, high + pad


def _model_of(model: Any) -> Any:
    """The :class:`CharacterModel` for what ``add_character`` was given as a model, or None."""
    if model is None:
        return None
    from OpenGLContext.character.model import CharacterModel  # noqa: PLC0415 only a character with a body needs it

    if isinstance(model, (bytes, bytearray, str, os.PathLike)):
        return CharacterModel.load(model)
    if hasattr(model, 'sceneGraph') and not hasattr(model, 'mixer'):
        return CharacterModel.from_scene(model)
    return model


def _clip_map_of(animations: Any, model: Any) -> Any:
    """The :class:`ClipMap` ``animations`` names, or None for none."""
    if animations is None or model is None:
        return None
    from OpenGLContext.character.locomotion import ClipMap  # noqa: PLC0415 only a character with a body needs it

    if isinstance(animations, ClipMap):
        return animations
    if animations == 'ual':
        return ClipMap.ual()
    if animations == 'guess':
        return ClipMap.guess(model)
    raise ValueError("animations is a ClipMap, 'ual' or 'guess', not %r" % (animations,))
