"""Background-threaded physics for the scenegraph.

:class:`ThreadedPhysicsManager` is a :class:`~OpenGLContext.physics.manager.PhysicsManager`
whose simulation runs off the render thread. It drives an
:class:`omi_physics.threaded.ThreadedSimulation` (which steps the world and
publishes an immutable pose snapshot each tick) and, on the render thread, copies
the latest snapshot onto the scene ``Transform`` nodes. The render thread never
blocks on a step: because the native solver, narrow phase, and PyOpenGL draw calls
all release the GIL, the physics tick and the render pass genuinely overlap, so a
render loop can hold 60 fps while the simulation advances underneath.

Anything that changes the world from another thread is made with the loop
stopped (:meth:`stop`) or while holding :meth:`with_world`: adding a body,
moving one, pushing one. :meth:`~ThreadedPhysicsManager.remove`, a subscription
and :meth:`~OpenGLContext.physics.events.CollisionEvents.report_hit` take the
lock themselves, and it is re-entrant, so they may also be called while holding
it. A walker built with a body
(:class:`~OpenGLContext.move.physicsplatform.PhysicsViewPlatform` with
``body=True``) places that body in the world on every update, so it is updated
under :meth:`with_world` too.

Collision subscriptions (:attr:`~OpenGLContext.physics.manager.PhysicsManager.events`)
are delivered on the render thread by :meth:`~ThreadedPhysicsManager.advance`,
with the snapshot the events were published alongside. A removed body's
``'end'`` events are published as it is removed, so they are delivered by the
next :meth:`~ThreadedPhysicsManager.advance` whether or not a tick has run.
"""
from typing import Any

from .manager import PhysicsManager, write_pose
from omi_physics.threaded import ThreadedSimulation


class ThreadedPhysicsManager(PhysicsManager):
    """A :class:`PhysicsManager` whose simulation runs on a background thread."""

    #: Steps run on the simulation thread, so an immediate subscription is refused.
    steps_on_this_thread = False

    def __init__(self, world: Any = None, gravity: Any = None,
                 sim_hz: float = 120.0, **kw: Any) -> None:
        super().__init__(world=world, gravity=gravity, **kw)
        self._sim = ThreadedSimulation(self.world, sim_hz=sim_hz)
        self._synced_version = -1
        #: Bodies added since the snapshot the render thread may still adopt,
        #: and the version of that snapshot: its row for their slot belongs
        #: to whatever was there before.
        self._fresh: dict[Any, int] = {}

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Begin simulating on a daemon thread (idempotent)."""
        self._sim.start()

    def stop(self) -> None:
        """Stop the simulation thread and wait for it to exit."""
        self._sim.stop()

    def with_world(self) -> Any:
        """Context manager giving exclusive access to the world (pauses stepping).

        Re-entrant: code holding it may remove a body or report a hit, which
        take it themselves.
        """
        return self._sim.with_world()

    @property
    def steps(self) -> int:
        """Total simulation ticks executed since the thread started."""
        return self._sim.steps

    @property
    def dropped(self) -> int:
        """Ticks abandoned because the previous one overran its budget."""
        return self._sim.dropped

    @property
    def sim_hz(self) -> float:
        """The tick rate asked for, to be read against :meth:`rate`."""
        return float(self._sim.sim_hz)

    def rate(self) -> float:
        """Ticks per second the thread is actually achieving.

        Well below :attr:`sim_hz` means the simulation is not getting the turns
        it asked for, which on screen is a world that moves in slow motion --
        indistinguishable from wrong physics until this number is on the panel
        next to it. Pair with :func:`OpenGLContext.ui.debugoverlay.simulation_provider`.
        """
        return self._sim.rate()

    def add(self, body: Any) -> Any:
        """Register ``body``, made with the loop stopped or under :meth:`with_world`."""
        super().add(body)
        self._fresh[body] = self._sim.latest()[1]
        return body

    def _forget(self, body: Any) -> None:
        """Stop tracking ``body``."""
        super()._forget(body)
        self._fresh.pop(body, None)

    def _remove_body(self, index: int) -> None:
        """Remove body ``index`` between two ticks, and publish what that ended."""
        with self.with_world():
            self.world.remove_body(index)
            self._sim.flush_events()

    # -- render thread ---------------------------------------------------
    def advance(self, real_dt: float) -> float:
        """Render-thread entry point: publish the latest poses, then deliver collisions.

        No stepping happens here. The events delivered are those published up
        to the snapshot written.
        """
        snap, version, events = self._sim.latest_and_events()
        self._write(snap, version)
        if self.events.draining:
            self.events.dispatch(events)
        return 1.0

    def sync(self, alpha: float = 1.0, force: bool = False) -> None:
        """Copy the latest published poses onto the scene Transforms.

        A no-op when no new tick has been published since the last sync (unless
        ``force``): the scene already shows the current poses, so re-writing every
        Transform would only burn the render thread's GIL time -- which, at very
        high body counts where a tick is slower than a frame, is exactly what would
        starve the simulation thread.
        """
        snap, version = self._sim.latest()
        self._write(snap, version, force)

    def _write(self, snap: Any, version: int, force: bool = False) -> None:
        """Write snapshot ``snap`` onto the Transforms, unless it is already written."""
        if snap is None or (version == self._synced_version and not force):
            return
        self._synced_version = version
        pos, aa, awake, dynamic = snap
        m = len(pos)
        fresh = self._fresh
        if fresh:
            for body in [body for body, before in fresh.items() if version > before]:
                del fresh[body]
        for body in self._bodies:
            i = body.index
            if (i is None or i >= m or body in fresh
                    or (dynamic[i] and not awake[i])):
                continue
            write_pose(body.transform, pos[i], aa[i])
