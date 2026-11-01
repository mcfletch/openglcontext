"""Which bodies meet: collision filters by system, and a contact filter asked as two bodies meet.

A body's ``collision_filter=`` option takes a
:class:`~OpenGLContext.physics.types.CollisionFilter`: the systems the body is a member of,
and the systems it collides with or not. Two bodies collide only where each
filter allows the other::

    balls = CollisionFilter(collisionSystems=('ball',))
    shards = CollisionFilter(collisionSystems=('shard',), notCollideWithSystems=('ball',))
    physics.add_dynamic(ball, collision_filter=balls)
    physics.add_dynamic(shard, collision_filter=shards)     # the ball passes through

:class:`Filters` gives each distinct filter its index in the world and sends it
there once. ``physics.set_contact_filter(function)`` asks ``function`` about each
pair as it first touches, with an :class:`Approach`; False lets the two pass
through each other until they part; the engine adapter asks it on the stepping thread.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from OpenGLContext.physics.types import CollisionFilter

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body

__all__ = ['Approach', 'Filters']


class Filters:
    """The collision filters a service has sent to its world, in the world's order."""

    def __init__(self, send: Callable[[int, CollisionFilter], None]) -> None:
        self._send = send
        self._known: list[CollisionFilter] = []

    def index(self, value: Any) -> int:
        """The world's index for ``value``: a ``CollisionFilter``, an index, or None for no filter.

        A filter the service has not sent before is sent now; an object with
        the fields of a ``CollisionFilter`` is taken as one. An int is an index
        into the filters already sent.
        """
        if value is None:
            return -1
        if not isinstance(value, (int, np.integer)):
            value = CollisionFilter.coerce(value)
            for number, known in enumerate(self._known):
                if known == value:
                    return number
            self._known.append(value)
            self._send(len(self._known) - 1, value)
            return len(self._known) - 1
        return int(value)


@dataclass(frozen=True, slots=True)
class Approach:
    """Two bodies about to meet for the first time, as a contact filter is told of them.

    ``first`` and ``second`` are the bodies, None for one with no handle (a
    body of an instance set); a character's stand-in is its character's
    ``body``. ``approach`` is the
    closing speed in metres a second, ``impulse`` the momentum the blow carries
    in newton-seconds, ``point`` where they meet and ``normal`` the unit vector
    from ``first`` toward ``second``.
    """
    first: Body | None
    second: Body | None
    approach: float
    impulse: float
    point: np.ndarray
    normal: np.ndarray
