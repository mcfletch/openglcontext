"""OmiEngine: the omi_physics world, stepped inline in the frame or on a Python thread.

The world and its commands are a
:class:`~OpenGLContext.physics.runtime.WorldRuntime`, stepped by one of the
workers of :mod:`~OpenGLContext.physics.worker`. Queries on the render thread
read the service's copy of the bodies
(:class:`~OpenGLContext.physics.replica.Replica`); inline, and on the stepping
thread, they read the world itself. A character is an omi_physics controller
stepped by the frame against the replica, with a kinematic stand-in in the
world (:mod:`~OpenGLContext.physics.character`).
"""
from __future__ import annotations

import concurrent.futures
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.physics import omi_adapter, queries
from OpenGLContext.physics.engine import Engine, LivePose, Outbox, RawHit
from OpenGLContext.physics.records import Command, Snapshot
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.types import EngineInfo
from OpenGLContext.physics.worker import InlineWorker, ThreadWorker, Worker

if TYPE_CHECKING:
    from OpenGLContext.physics.proxy import Proxy

__all__ = ['OmiEngine']

#: The seconds the first read of a joint on a world with its own thread waits for the thread.
JOINT_WAIT = 0.5


class OmiEngine(Engine):
    """An omi_physics world and the worker that steps it."""

    name = 'omi'
    stand_ins = True

    def __init__(self, definition: PhysicsDefinition, wake: Callable[[], Any] | None = None) -> None:
        super().__init__(definition)
        self._wake = wake
        self.worker: Worker = self._make_worker(definition.mode, None)
        runtime = self.worker.runtime
        runtime.on_events = self.on_events
        runtime.before_step = self.before_step
        runtime.after_step = self.after_step
        runtime.wants_steps = self.wants_steps

    def _make_worker(self, mode: str, runtime: Any) -> Worker:
        if mode == 'inline':
            return InlineWorker(self.definition, runtime=runtime)
        return ThreadWorker(self.definition, wake=self._wake, runtime=runtime)

    @property
    def runtime(self) -> Any:
        """The worker's :class:`~OpenGLContext.physics.runtime.WorldRuntime`."""
        return self.worker.runtime

    # -- stepping -------------------------------------------------------
    @property
    def error(self) -> BaseException | None:
        return self.worker.error

    @property
    def step_dt(self) -> float:
        return float(self.worker.runtime.step_dt)

    @property
    def max_catch_up(self) -> float:
        return float(self.worker.runtime.max_catch_up)

    def on_engine_thread(self) -> bool:
        return self.worker.on_worker_thread()

    def submit(self, command: Command) -> None:
        self.worker.submit(command)

    def collect(self, dt: float) -> Outbox:
        out = self.worker.collect(dt)
        return Outbox(out.snapshot, out.events)

    def step(self, dt: float) -> None:
        self.worker.step(dt)

    def flush(self) -> None:
        self.worker.flush()

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> bool:
        return self.worker.stop()

    @property
    def mode(self) -> str:
        return 'inline' if isinstance(self.worker, InlineWorker) else 'thread'

    def set_mode(self, mode: str) -> None:
        """Step in ``mode`` from now on, carrying the waiting commands over in order.

        Raises RuntimeError, leaving the worker as it is, where its thread is
        still in a step once the worker's stop has waited for it.
        """
        if mode == self.mode:
            return
        old = self.worker
        if not old.stop():
            raise RuntimeError('the physics thread is still in its step; the world stays '
                               'on it in %s mode' % self.mode)
        pending = old.inbox.drain()
        new = self._make_worker(mode, old.runtime)
        for command in pending:
            new.inbox.post(command)
        self.worker = new

    def callbacks_changed(self) -> None:
        """Nothing: the omi runtime asks for its hooks at every step."""

    def pin(self, on: bool) -> None:
        """Nothing: the service holds an omi world inline by switching it to the inline worker."""

    def live_time(self) -> float:
        return float(self.worker.runtime.world.time)

    def character_steps(self, dt: float) -> tuple[int, float]:
        worker = self.worker
        if isinstance(worker, InlineWorker):
            return worker.owed, worker.runtime.clock.alpha
        raise AssertionError('the service counts the steps of a threaded world itself')

    def info(self) -> EngineInfo:
        return omi_adapter.engine_info(float(self.definition.tickHz),
                                       str(self.worker.runtime.world.backend.name))

    # -- reading on the stepping thread ----------------------------------
    def live_poses(self, uids: Sequence[int]) -> dict[int, LivePose]:
        runtime = self.worker.runtime
        world = runtime.world
        found = {}
        for uid in uids:
            if uid not in runtime:
                continue
            index = runtime.entry(uid).index
            found[uid] = LivePose(world.position[index].copy(), world.orientation[index].copy(),
                                  world.linear_velocity[index].copy(),
                                  world.angular_velocity[index].copy(),
                                  not bool(world.awake[index]) and int(world.motion_type[index]) == 2)
        return found

    def joint_reading(self, joint: Any, published: Snapshot | None) -> tuple[float, ...]:
        from OpenGLContext.physics.joints import READINGS  # noqa: PLC0415 joints import the service

        worker = self.worker
        none = (0.0,) * (len(joint.spec.axes) if joint.kind == 'motor'
                         else len(READINGS.get(joint.kind, ())))
        if worker.on_worker_thread() or isinstance(worker, InlineWorker):
            if not worker.on_worker_thread():
                worker.flush()
            runtime = worker.runtime
            return runtime.joints.reading(runtime.world, joint.uid) if joint.uid in runtime.joints else none
        if not joint._watched:
            joint._watched = True
            if joint.alive:
                worker.submit(Command('joint_watch', joint.body.uid, (joint.uid,)))
            runtime = worker.runtime
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            worker.submit(Command('run', 0, (lambda _world: runtime.joints.reading(
                runtime.world, joint.uid) if joint.uid in runtime.joints else none, future)))
            worker.flush()
            try:
                return tuple(future.result(timeout=JOINT_WAIT))
            except concurrent.futures.TimeoutError:
                return none
        found = None if published is None else published.joints.get(joint.uid)
        return none if found is None else found

    # -- queries ----------------------------------------------------------
    def _queryable(self) -> tuple[Any, Callable[[int], int | None], Callable[[int], int | None]]:
        """The world this thread may read, and how to turn body ids into its slots and back.

        An inline world is read live; a world on a thread through the replica.
        """
        live = self.worker.on_worker_thread()
        if live or isinstance(self.worker, InlineWorker):
            if not live:
                self.worker.flush()
            runtime = self.worker.runtime
            world = runtime.world

            def slot(uid: int) -> int | None:
                return runtime.entry(uid).index if uid in runtime else None

            def uid_at(index: int) -> int | None:
                handle = world.handle_of(world.ref(index))
                return None if handle is None else int(handle)

            return world, slot, uid_at
        assert self.replica is not None
        replica = self.replica()
        return (replica.world, lambda uid: replica._index.get(uid), replica.uid_at)

    @staticmethod
    def _slots(skip: set[int], slot: Callable[[int], int | None]) -> set[int]:
        return {index for index in (slot(uid) for uid in skip) if index is not None}

    @staticmethod
    def _raw(found: Any, uid_at: Callable[[int], int | None]) -> RawHit:
        return RawHit(uid_at(int(found.body)), np.asarray(found.point), np.asarray(found.normal),
                      float(found.distance), int(found.triangle))

    def raycast(self, origin: Any, direction: Any, max_distance: float,
                skip: set[int]) -> RawHit | None:
        world, slot, uid_at = self._queryable()
        found = queries.raycast(world, origin, direction, float(max_distance), self._slots(skip, slot))
        return None if found is None else self._raw(found, uid_at)

    def raycast_many(self, origins: Any, directions: Any, max_distance: float,
                     skip: set[int]) -> list[RawHit | None]:
        world, slot, uid_at = self._queryable()
        found = queries.raycast_many(world, origins, directions, float(max_distance),
                                     self._slots(skip, slot))
        return [None if one is None else self._raw(one, uid_at) for one in found]

    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: set[int]) -> float | None:
        world, slot, _uid_at = self._queryable()
        return queries.sweep_sphere(world, origin, direction, float(distance), float(radius),
                                    self._slots(skip, slot))

    def overlap(self, proxy: Proxy, translation: Any, quaternion: Any, skip: set[int],
                triggers: bool) -> list[int]:
        world, slot, uid_at = self._queryable()
        found = queries.overlapping(world, proxy, translation, quaternion,
                                    self._slots(skip, slot), triggers)
        return [uid for uid in (uid_at(index) for index in found) if uid is not None]

    # -- the contact filter ---------------------------------------------------
    def set_contact_filter(self, function: Callable[[Any], Any] | None) -> None:
        made = None if function is None else omi_adapter.ContactFilter(function, self._body_of_ref)
        self.submit(Command('contact_filter', 0, (made,)))

    def _body_of_ref(self, ref: Any) -> Any:
        """The service's body an omi world reference names, on the stepping thread."""
        uid = self.worker.runtime.world.handle_of(ref)
        return None if uid is None else self.body_of(int(uid))

    # -- characters -------------------------------------------------------
    def make_character(self, physics: Any, centre: np.ndarray, capabilities: Any,
                       gravity: float) -> tuple[Any, Any]:
        from omi_physics.character import CharacterController  # noqa: PLC0415 only a character needs it

        replica = physics._character_replica()
        body = physics._add_standin(centre, capabilities, CharacterController.PUSH_REACH)
        controller = CharacterController(
            replica.query, omi_adapter.omi_capabilities(capabilities), centre, gravity=gravity,
            ignore=[replica.index_of(body.uid), *physics.passable_slots()])
        return body, controller
