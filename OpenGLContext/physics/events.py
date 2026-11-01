"""Collision: one collision, as the body whose handler is called sees it.

The physics service (:mod:`OpenGLContext.physics.service`) delivers one
:class:`Collision` to each handler a body registered with
:meth:`Body.addEventHandler <OpenGLContext.physics.body.Body.addEventHandler>`,
once a frame on the render thread or on the physics thread for a handler marked
:func:`~OpenGLContext.physics.callbacks.physics_callback`::

    def thud(hit):
        audio.play('thud.ogg', at=hit.point, gain=min(1.0, hit.speed / 4.0))

    crate.addEventHandler('hit', function=thud, above=0.5)

See ``docs/physics.rst``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ['Collision']


@dataclass(frozen=True, slots=True)
class Collision:
    """One collision, as the subscribed body sees it.

    ``normal`` points from ``other`` into ``body``: the direction ``body`` was
    pushed. For a trigger event it is zero, since an overlap has no direction,
    and ``point`` is where the body that entered was on the step it did.
    """
    #: ``'contact'``, ``'trigger'`` or ``'hit'``.
    kind: str
    #: ``'begin'``, ``'persist'`` or ``'end'`` for a contact; ``'enter'``,
    #: ``'stay'`` or ``'exit'`` for a trigger; ``'begin'`` for a hit.
    phase: str
    #: The side whose handler is called: its
    #: :class:`~OpenGLContext.physics.body.Body`, or None for a body with no
    #: handle (a character's stand-in, a body of an instance set).
    body: Any
    #: The other side, named the same way.
    other: Any
    #: The node each side moves, or None.
    node: Any
    other_node: Any
    point: np.ndarray
    normal: np.ndarray
    #: Closing speed along the normal before the solve, m/s; zero for a
    #: trigger and on an ``'end'``.
    approach: float
    #: Normal impulse, N·s: what a breaking strength compares against.
    impulse: float
    #: Friction impulse, N·s, and sliding speed, m/s: scraping.
    friction_impulse: float
    slip: float
    #: Deepest penetration, m.
    depth: float
    #: Simulation time of the step, s: when to schedule a sound.
    time: float
    #: False where a contact filter let the pair pass through each other.
    solved: bool
    #: On an ``'end'``, ``'separated'`` or ``'removed'``.
    reason: str | None
    #: What the event carried beside the collision, or None.
    payload: Any
    #: The :class:`~OpenGLContext.physics.records.PhysicsEvent` this was made from.
    event: Any = field(repr=False)
    #: The world's step count when it happened, which orders events within
    #: a frame and says which step of a frame made one.
    step: int = 0

    @property
    def speed(self) -> float:
        """The closing speed along the normal, m/s: :attr:`approach`."""
        return self.approach
