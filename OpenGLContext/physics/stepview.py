"""StepView: what tick-exact code is given after each fixed step.

:meth:`Physics.on_step <OpenGLContext.physics.service.Physics.on_step>`
registers a function that the stepping thread calls after every step with a
:class:`StepView`. The view offers the step record, bulk reads of bodies and the
queries, all answered from the world as the step left it. Writes go through
:class:`~OpenGLContext.physics.body.Body` handles, which apply at once on the
stepping thread, and through :meth:`StepView.post` for anything else::

    magnet = physics.add_static(None, proxy=Proxy.sphere(0.2), translation=(0, 1, 0))

    def pull(view):
        poses = view.poses(balls)
        for ball, at in zip(balls, poses.position):
            ball.apply_impulse((magnet_at - at) * view.dt)

    physics.on_step(pull)

The view holds no engine object, so the same function runs whichever engine
steps the world.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.types import Hit
    from OpenGLContext.physics.records import Step
    from OpenGLContext.physics.service import Physics
    from OpenGLContext.physics.types import Poses

__all__ = ['StepHook', 'StepView']


@dataclass(eq=False, slots=True)
class StepHook:
    """A function :meth:`Physics.on_step` calls after each step, until :meth:`cancel`."""
    function: Callable[[StepView], Any]
    cancelled: bool = False
    #: Whether the function has raised, so its failure is logged once.
    failed: bool = field(default=False, repr=False)

    def cancel(self) -> None:
        """Stop calling the function, from the next step."""
        self.cancelled = True


class StepView:
    """One fixed step as tick-exact code sees it: the step, reads and queries of the world."""

    __slots__ = ('_physics', 'step')

    def __init__(self, physics: Physics, step: Step) -> None:
        self._physics = physics
        #: The step just taken: its length ``dt``, its ``index`` and the ``time`` it began.
        self.step = step

    @property
    def dt(self) -> float:
        """The step's length, in seconds."""
        return self.step.dt

    @property
    def time(self) -> float:
        """The world's clock at the end of the step, in seconds."""
        return self.step.time + self.step.dt

    def poses(self, bodies: Iterable[Body | int]) -> Poses:
        """The poses, velocities and masses of ``bodies`` as the step left them; see :meth:`Physics.poses`."""
        return self._physics.poses(bodies, interpolated=False)

    def raycast(self, origin: Any, direction: Any, max_distance: float = 100.0,
                skip: Any = None) -> Hit | None:
        """What a ray meets first, or None; see :meth:`Physics.raycast`."""
        return self._physics.raycast(origin, direction, max_distance, skip)

    def raycast_many(self, origins: Any, directions: Any, max_distance: float = 100.0,
                     skip: Any = None) -> list[Hit | None]:
        """Several rays at once; see :meth:`Physics.raycast_many`."""
        return self._physics.raycast_many(origins, directions, max_distance, skip)

    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: Any = None) -> float | None:
        """How far a sphere travels before it touches a body; see :meth:`Physics.sweep_sphere`."""
        return self._physics.sweep_sphere(origin, direction, distance, radius, skip)

    def overlap(self, proxy: Any, translation: Any, rotation: Any = None, skip: Any = None,
                triggers: bool = False) -> list[Body]:
        """The bodies a shape placed here overlaps; see :meth:`Physics.overlap`."""
        return self._physics.overlap(proxy, translation, rotation, skip, triggers)

    def post(self, function: Callable[..., Any], *arguments: Any) -> None:
        """Call ``function(*arguments)`` before the next step; see :meth:`Physics.post`."""
        self._physics.post(function, *arguments)
