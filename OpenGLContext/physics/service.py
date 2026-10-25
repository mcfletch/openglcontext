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
import dataclasses
import itertools
import logging
import os
import queue
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from omi_physics import mathutil, model
from omi_physics.gravity import GravityVolume
from omi_physics.collisionquery import WorldQuery

from OpenGLContext.events.handoff import Updates
from OpenGLContext.physics.body import Body
from OpenGLContext.physics.character import Character, stand_in_proxy
from OpenGLContext.physics.callbacks import is_physics_callback
from OpenGLContext.physics.colliders import SceneryTracker
from OpenGLContext.physics.events import Collision
from OpenGLContext.physics.handlers import NAME_OF, STEP_EVENTS, Handler, HandlerTable
from OpenGLContext.physics.materials import Materials
from OpenGLContext.physics.manager import write_pose
from OpenGLContext.physics.proxy import DEFAULT_DENSITY, Proxy
from OpenGLContext.physics.queries import Hit, overlapping, sweep_sphere
from OpenGLContext.physics.replica import Replica, build
from OpenGLContext.physics.records import BodyBatch, BodySpec, Command, PhysicsEvent, Step
from OpenGLContext.physics.sources import SourceHandle
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.worker import InlineWorker, ThreadWorker, Worker
from OpenGLContext.scenegraph.physicsbody import quat_to_vrml_rotation, vrml_rotation_to_quat

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
                 mount: Callable[[Any, bool], Any] | None = None) -> None:
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
        self.scenery = SceneryTracker(self)
        #: The spec of each body in the world, to build the replica from when queries need it.
        self._specs: dict[int, BodySpec] = {}
        self._replica: Replica | None = None
        self._characters: list[Character] = []
        self._sources: list[SourceHandle] = []
        self._cooker: concurrent.futures.ThreadPoolExecutor | None = None
        self._cooked_results: queue.SimpleQueue[tuple[Body, BodySpec | None]] = queue.SimpleQueue()
        self._outstanding = 0
        #: How many scenery shapes have been cooked.
        self.cooked = 0

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
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    @property
    def world(self) -> Any:
        """The live :class:`omi_physics.world.PhysicsWorld`, in inline mode only.

        A world stepped on a thread is reached with :meth:`run`.
        """
        return self._inline().runtime.world

    def _inline(self) -> InlineWorker:
        """The worker, where it steps inline; RuntimeError where it has a thread."""
        if isinstance(self.worker, InlineWorker):
            return self.worker
        raise RuntimeError('physics.world is for inline mode; use physics.run(fn) to reach '
                           'the world on its thread')

    def slot_of(self, body: Body) -> int:
        """The row ``body`` has in the arrays of :attr:`world`, inline mode only.

        Waiting commands are applied first, so a body added a moment ago has
        its row. Raises KeyError for a body the world does not hold.
        """
        worker = self._inline()
        worker.flush()
        return int(worker.runtime.entry(body.uid).index)

    def body_at(self, slot: int) -> Body | None:
        """The body in row ``slot`` of the arrays of :attr:`world`, or None for a row no body has."""
        world = self._inline().runtime.world
        if not 0 <= slot < len(world.bodies):
            return None
        uid = world.handle_of(world.ref(slot))
        return None if uid is None else self._bodies.get(int(uid))

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

    def _add(self, kind: str, node: Any, proxy: Any, options: dict[str, Any], *,
             motion: model.Motion | None = None,
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
        if node is None:
            if not isinstance(proxy, (Proxy, model.Shape)):
                raise TypeError('a body with no node needs a shape: proxy=Proxy.box(...), '
                                'Proxy.trimesh(...) or another Proxy constructor')
            shape = proxy if isinstance(proxy, Proxy) else Proxy(proxy)
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
        if motion is None:
            mass = 0.0
            if dynamic:
                mass = float(options['mass']) if options.get('mass') is not None else shape.mass(
                    float(options.get('density') or DEFAULT_DENSITY))
            motion = model.Motion(
                type={'dynamic': model.DYNAMIC, 'kinematic': model.KINEMATIC}.get(
                    kind, model.STATIC),
                mass=mass if dynamic else 1.0,
                linearDamping=float(self.definition.linearDamping if linear is None else linear),
                angularDamping=float(self.definition.angularDamping if angular is None else angular))
        mass = float(motion.mass) if dynamic else 0.0
        uid = next(self._uids)
        material = self._material(options)
        named = options.get('material') if isinstance(options.get('material'), str) else None
        sounding = self.materials.sound_of(named) is not None
        spec = BodySpec(uid, kind, shape, motion, tuple(position), quaternion, material,
                        int(options.get('collision_filter', -1)), report=sounding)
        body = Body(self, uid, kind, node, shape, position, axis_angle, mass,
                    motion.linearDamping, motion.angularDamping)
        body.derived = derived
        body.material = named
        if sounding:
            self._send_world('logging', True)
        self._bodies[uid] = body
        if node is not None:
            self._by_node[node] = body
        if kind in ('dynamic', 'kinematic'):
            self._movers.append(body)
        if self._enabled and not self._closed:
            self._send(Command('add', uid, (spec,), next(self._seq)))
            if kind in ('dynamic', 'kinematic'):
                self._ensure_started()
        return body

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
            given if isinstance(given, model.Material) else model.Material())
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
            if self._enabled and not self._closed:
                self._send(Command('add', body.uid, (spec,), next(self._seq)))
                for op, args in deferred:
                    self._send(Command(op, body.uid, args, next(self._seq)))

    def add_ground(self, ground: Any, extent: Any = None, height_range: Any = None,
                   feature: float = 1.0, **options: Any) -> Body:
        """Make a static body of land that answers a height at each ``(x, z)``.

        ``ground`` is any object with ``sample(x, z)``, as a
        :class:`~OpenGLContext.scenegraph.vegetation.grid.Ground` has, so the
        surface a body meets is the one the terrain node draws. ``extent`` is
        ``((x_min, z_min), (x_max, z_max))`` or None for land without an edge;
        ``height_range`` is ``(lowest, highest)`` and is found by sampling a
        grid of the extent (or 1000 metres about the origin) when it is not given.
        ``feature`` is the horizontal distance over which the land changes
        appreciably. Options are the material options of :meth:`add_static`.
        """
        low, high = height_range if height_range is not None else _sampled_heights(ground, extent)
        shape = model.Shape.heightfield(sample=ground.sample, vectorized=True, extent=extent,
                                        height_range=(float(low), float(high)),
                                        feature=float(feature))
        return self._add_object('static', ground, Proxy(shape), options)

    def _add_object(self, kind: str, key: Any, proxy: Proxy, options: dict[str, Any]) -> Body:
        """A body for something that is not a scenegraph node, found by ``key``."""
        unknown = set(options) - self._OPTIONS
        if unknown:
            raise TypeError('unknown option %s' % ', '.join(sorted(unknown)))
        named = options.get('material')
        body = self._add_placed(kind, proxy, (0.0, 0.0, 0.0), None, self._material(options),
                                int(options.get('collision_filter', -1)),
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
        spec = BodySpec(uid, kind, proxy, model.Motion(type=model.STATIC), place, quaternion,
                        material, collision_filter, report=sounding)
        body = Body(self, uid, kind, None, proxy, np.asarray(place), quat_to_vrml_rotation(quaternion),
                    0.0)
        body.material = named
        if sounding:
            self._send_world('logging', True)
        self._bodies[uid] = body
        if self._enabled and not self._closed:
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
                          int(options.get('collision_filter', -1)))
        if self._enabled and not self._closed:
            self._send(Command('add_many', 0, (batch,), next(self._seq)))
        return StaticInstances(self, first, len(points))

    def add_gravity_zone(self, region: Any, gravity: Any = 9.81, toward: Any = None,
                         priority: int = 0, replace: bool = False, stop: bool = False) -> Any:
        """Change gravity inside ``region``, a :class:`~OpenGLContext.physics.zones.Box` or ``Sphere``.

        ``gravity`` is an acceleration vector, or a magnitude pointing down, or
        toward ``toward``, a point, where that is given. A higher ``priority``
        wins; ``replace`` drops the lower ones instead of adding to them, and
        ``stop`` ends the counting at this zone. Returns the volume.
        """
        values = np.atleast_1d(np.asarray(gravity, dtype='d'))
        if toward is not None:
            field = model.Gravity(type=model.POINT, gravity=float(values[0]), center=tuple(toward),
                                  priority=priority, replace=replace, stop=stop)
        elif values.size == 3:
            strength = float(np.linalg.norm(values))
            direction = (0.0, -1.0, 0.0) if strength == 0.0 else tuple(values / strength)
            field = model.Gravity(gravity=strength, direction=direction, priority=priority,
                                  replace=replace, stop=stop)
        else:
            field = model.Gravity(gravity=float(values[0]), priority=priority, replace=replace,
                                  stop=stop)
        volume = GravityVolume(field, region)
        self._send_world('gravity_zone', volume)
        return volume

    def zones_changed(self, placed: Any) -> bool:
        """Bring the world's zone gravity to the scene's zones, as the render pass places them.

        Returns whether they were other placements than last time.
        """
        from OpenGLContext.physics.zones import ZoneRegion, gravity_volumes  # noqa: PLC0415 imports the scenegraph
        from OpenGLContext.scenegraph.zone import GRAVITY  # noqa: PLC0415 imports the scenegraph

        carrying = tuple(zone for zone in placed if zone.setting(GRAVITY) is not None)
        if len(carrying) == len(self._zones_placed) and all(
                one is other for one, other in zip(carrying, self._zones_placed, strict=True)):
            return False
        self._zones_placed = carrying
        self._send_world('gravity_zones', ZoneRegion, gravity_volumes(carrying))
        return True

    def show_proxies(self, on: bool = True) -> None:
        """Draw the collision shapes, to see what the world collides with; False takes the drawing out."""
        from OpenGLContext.physics.debugdraw import PROXIES, PhysicsDebugDraw  # noqa: PLC0415 imports the scenegraph

        if on and self._overlay is None and self._mount is not None:
            self._overlay = PhysicsDebugDraw(self._character_replica().world, flags=PROXIES)
            self._overlay.update()
            self._mount(self._overlay.root, True)
        elif not on and self._overlay is not None:
            if self._mount is not None:
                self._mount(self._overlay.root, False)
            self._overlay = None

    def add_character(self, node: Any = None, capabilities: Any = None,
                      position: Any = (0.0, 0.0, 0.0), gravity: float | None = None, *,
                      model: Any = None, animations: Any = None, parent: Any = None,
                      fit: bool = True, facing: bool = True) -> Character:
        """Make a walker standing with its feet at ``position``.

        ``capabilities`` is a :class:`~omi_physics.character.CharacterCapabilities`
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
        character is doing.
        """
        from omi_physics.character import CharacterCapabilities  # noqa: PLC0415 only a service with walkers needs it

        caps = capabilities if capabilities is not None else CharacterCapabilities()
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

        made = Character(self, node, caps, position, pull, model=wearing, clip_map=clip_map,
                         facing=Facing() if facing and wearing is not None else None,
                         turn_node=turn)
        self._characters.append(made)
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

    def _character_replica(self) -> Replica:
        """The render thread's copy of the bodies, made on first use; characters step against it."""
        if self._replica is None:
            self._replica = build(self._specs, self._snapshot)
        return self._replica

    def _add_standin(self, centre: Any, capabilities: Any, reach: float) -> Body:
        """The kinematic body the world sees for a character, with no node."""
        proxy = stand_in_proxy(capabilities, reach)
        uid = next(self._uids)
        spec = BodySpec(uid, 'kinematic', proxy, model.Motion(type=model.KINEMATIC),
                        tuple(float(v) for v in centre), (0.0, 0.0, 0.0, 1.0), report=True)
        body = Body(self, uid, 'kinematic', None, proxy, np.asarray(centre, dtype='d'),
                    (0.0, 0.0, 1.0, 0.0), 0.0)
        self._bodies[uid] = body
        self._movers.append(body)
        if self._enabled and not self._closed:
            self._send(Command('add', uid, (spec,), next(self._seq)))
            self._ensure_started()
        return body

    def log_handler_failure(self, function: Callable[..., Any], argument: Any) -> None:
        """Log that a handler raised, once for each function."""
        log.exception('physics handler %r failed on %r', function, argument)

    def cook(self, node: Any, strategy: str = 'auto', dynamic: bool = True) -> Proxy:
        """A :class:`Proxy` cooked from what ``node`` draws, to share between bodies."""
        return Proxy.from_node(node, strategy, dynamic)

    def remove(self, body: Body) -> None:
        """Take ``body`` out of the world. Removing twice is harmless."""
        if not body.alive:
            return
        if self._enabled and not self._closed:
            seq = next(self._seq)
            self._send(Command('remove', body.uid, (), seq))
            self._gone.append((seq, body.uid))
        else:
            self.handlers.forget_body(body.uid)
        body.alive = False
        if body.derived:
            self.scenery.release(body.node)
        self._bodies.pop(body.uid, None)
        if body.node is not None and self._by_node.get(body.node) is body:
            del self._by_node[body.node]
        if body in self._movers:
            self._movers.remove(body)
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
        if not body.alive or not self._enabled or self._closed:
            return 0
        if body._pending:
            body._deferred.append((op, args))
            return 0
        seq = next(self._seq)
        self._send(Command(op, body.uid, args, seq))
        return seq

    def _send(self, command: Command) -> None:
        """Send ``command`` to the worker and keep the replica, where there is one, in step."""
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
        if self._replica is not None:
            self._replica.apply(command)
        self.worker.submit(command)

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

    def flush(self) -> None:
        """Apply the commands waiting for the world now, without stepping it.

        An inline or standalone service applies a write at the start of its next
        step; code that reads :attr:`world` between steps calls this first to see
        the writes it has just made. A service whose thread is running applies
        them on that thread, and this leaves them there.
        """
        self.worker.flush()

    def index_of(self, body: Body) -> int:
        """The slot of ``body`` in the arrays of :attr:`world`, inline mode only.

        Commands waiting for the world are applied first, so a body added a moment
        ago has its slot. Raises KeyError for a body the world does not hold.
        """
        if not isinstance(self.worker, InlineWorker):
            raise RuntimeError('physics.index_of is for inline mode; the world is on its own thread')
        self.flush()
        return int(self.worker.runtime.entry(body.uid).index)

    def drop_remainder(self) -> None:
        """Forget the time carried over toward the next step.

        An inline or standalone service steps whole ticks and carries what is
        left of a frame to the next; a game that starts something afresh calls
        this so the leftover is not simulated into it.
        """
        self._send_world('drop_remainder')

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
        self._pump_cooked()
        out = self.worker.collect(dt)
        if out.snapshot is not None:
            self._snapshot = out.snapshot
            if self._replica is not None:
                self._replica.sync(out.snapshot)
                if self._overlay is not None:
                    self._overlay.update()
            self._write_poses(out.snapshot)
            moving = out.snapshot.awake & (out.snapshot.dynamic | (
                np.abs(out.snapshot.linear_velocity).sum(axis=1) > 0.0))
            self._awake = bool(moving.any())
        for handle in list(self._sources):
            handle.update()
        walking = False
        for character in list(self._characters):
            if character.framed:
                character.update(dt)
                walking = walking or character.busy
        if out.events:
            self._dispatch(out.events)
        self._finish_removals()
        applied = self.render.apply()
        return bool(self._awake or applied or walking)

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
            if body.node is None:
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

    # -- queries ---------------------------------------------------------
    def _queryable(self) -> tuple[Any, Callable[[int], int | None], Callable[[int], int | None]]:
        """The world this thread may read, and how to turn body ids into its slots and back.

        An inline service is read live. A service on a thread is read through
        the replica, made on first use.
        """
        if isinstance(self.worker, InlineWorker):
            self.worker.flush()
            runtime = self.worker.runtime
            world = runtime.world

            def slot(uid: int) -> int | None:
                return runtime.entry(uid).index if uid in runtime else None

            def uid_at(index: int) -> int | None:
                handle = world.handle_of(world.ref(index))
                return None if handle is None else int(handle)

            return world, slot, uid_at
        if self._replica is None:
            self._replica = build(self._specs, self._snapshot)
        replica = self._replica
        return (replica.world, lambda uid: replica._index.get(uid), replica.uid_at)

    @staticmethod
    def _skipped(skip: Any, slot: Callable[[int], int | None]) -> set[int]:
        if skip is None:
            return set()
        bodies = [skip] if isinstance(skip, Body) else list(skip)
        return {index for index in (slot(body.uid) for body in bodies) if index is not None}

    def raycast(self, origin: Any, direction: Any, max_distance: float = 100.0,
                skip: Any = None) -> Hit | None:
        """What a ray from ``origin`` along ``direction`` meets first, or None.

        Answers in the call, from the world as the last tick left it. ``skip``
        is a body, or a list of them, the ray passes through.
        """
        world, slot, uid_at = self._queryable()
        found = WorldQuery(world).raycast(origin, direction, float(max_distance),
                                          self._skipped(skip, slot))
        return None if found is None else self._hit(found, uid_at)

    def raycast_many(self, origins: Any, directions: Any, max_distance: float = 100.0,
                     skip: Any = None) -> list[Hit | None]:
        """Several rays at once, each answered as :meth:`raycast` would answer it."""
        from omi_physics.raycast import raycast_many  # noqa: PLC0415 only a service that casts needs it

        world, slot, uid_at = self._queryable()
        found = raycast_many(world, origins, directions, float(max_distance),
                             self._skipped(skip, slot))
        return [None if one is None else self._hit(one, uid_at) for one in found]

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

    def _hit(self, found: Any, uid_at: Callable[[int], int | None]) -> Hit:
        uid = uid_at(int(found.body))
        return Hit(None if uid is None else self._body_of(uid), np.asarray(found.point),
                   np.asarray(found.normal), float(found.distance), int(found.triangle))

    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: Any = None) -> float | None:
        """How far a sphere of ``radius`` travels along ``direction`` before it touches a body.

        None where it travels ``distance`` clear; 0 where it starts inside a body.
        """
        world, slot, _uid_at = self._queryable()
        return sweep_sphere(world, origin, direction, float(distance), float(radius),
                            self._skipped(skip, slot))

    def overlap(self, proxy: Any, translation: Any, rotation: Any = None,
                skip: Any = None, triggers: bool = False) -> list[Body]:
        """The bodies a shape overlaps when placed at ``translation``, turned by ``rotation``.

        ``proxy`` is a :class:`Proxy` or a :class:`~omi_physics.model.Shape`;
        ``rotation`` is an axis and an angle. The answer lists solid bodies, or
        with ``triggers=True`` the trigger volumes the shape is in.
        """
        world, slot, uid_at = self._queryable()
        shape = proxy.shape if isinstance(proxy, Proxy) else proxy
        quaternion = (np.array([0.0, 0.0, 0.0, 1.0]) if rotation is None
                      else vrml_rotation_to_quat(rotation))
        found = overlapping(world, shape, translation, quaternion, self._skipped(skip, slot),
                            triggers)
        bodies = [self._body_of(uid) for uid in (uid_at(index) for index in found)
                  if uid is not None]
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
        """The exception that stopped the worker, or None."""
        return getattr(self.worker, 'error', None)

    def close(self) -> None:
        """Stop the worker and let go of the bodies. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self._cooker is not None:
            self._cooker.shutdown(wait=False, cancel_futures=True)
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
