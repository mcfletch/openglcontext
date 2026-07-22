"""Background-threaded physics for the scenegraph.

:class:`ThreadedPhysicsManager` is a :class:`~OpenGLContext.physics.manager.PhysicsManager`
whose simulation runs off the render thread. It drives an
:class:`omi_physics.threaded.ThreadedSimulation` (which steps the world and
publishes an immutable pose snapshot each tick) and, on the render thread, copies
the latest snapshot onto the scene ``Transform`` nodes. The render thread never
blocks on a step: because the native solver, narrow phase, and PyOpenGL draw calls
all release the GIL, the physics tick and the render pass genuinely overlap, so a
render loop can hold 60 fps while the simulation advances underneath.

Structural changes to the world (adding/removing bodies) must be made with the
loop stopped (:meth:`stop`) or while holding :meth:`with_world`.
"""
from typing import Any

from .manager import PhysicsManager, write_pose
from omi_physics.threaded import ThreadedSimulation


class ThreadedPhysicsManager(PhysicsManager):
    """A :class:`PhysicsManager` whose simulation runs on a background thread."""

    def __init__(self, world: Any = None, gravity: Any = None,
                 sim_hz: float = 120.0, **kw: Any) -> None:
        super().__init__(world=world, gravity=gravity, **kw)
        self._sim = ThreadedSimulation(self.world, sim_hz=sim_hz)
        self._synced_version = -1

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Begin simulating on a daemon thread (idempotent)."""
        self._sim.start()

    def stop(self) -> None:
        """Stop the simulation thread and wait for it to exit."""
        self._sim.stop()

    def with_world(self):
        """Context manager giving exclusive access to the world (pauses stepping)."""
        return self._sim.with_world()

    @property
    def steps(self) -> int:
        """Total simulation ticks executed since the thread started."""
        return self._sim.steps

    # -- render thread ---------------------------------------------------
    def advance(self, real_dt: float) -> float:
        """Render-thread entry point: publish the latest poses (no stepping here)."""
        self.sync()
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
        if snap is None or (version == self._synced_version and not force):
            return
        self._synced_version = version
        pos, aa, awake, dynamic = snap
        m = len(pos)
        for body in self.bodies:
            i = body.index
            if i is None or i >= m or (dynamic[i] and not awake[i]):
                continue
            write_pose(body.transform, pos[i], aa[i])
