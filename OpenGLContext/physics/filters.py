"""Which bodies meet: collision filters by system, and a contact filter asked as two bodies meet.

A body's ``collision_filter=`` option takes a
:class:`~omi_physics.model.CollisionFilter`: the systems the body is a member of,
and the systems it collides with or not. Two bodies collide only where each
filter allows the other::

    balls = CollisionFilter(collisionSystems=('ball',))
    shards = CollisionFilter(collisionSystems=('shard',), notCollideWithSystems=('ball',))
    physics.add_dynamic(ball, collision_filter=balls)
    physics.add_dynamic(shard, collision_filter=shards)     # the ball passes through

:class:`Filters` gives each distinct filter its index in the world and sends it
there once. ``physics.set_contact_filter(function)`` asks ``function`` about each
pair as it first touches, with an :class:`Approach`; False lets the two pass
through each other until they part. :class:`ContactFilter` is the worker's side.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import model
from omi_physics.contactevents import PairPreview, Verdict

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body

__all__ = ['Approach', 'ContactFilter', 'Filters']

log = logging.getLogger(__name__)


class Filters:
    """The collision filters a service has sent to its world, in the world's order."""

    def __init__(self, send: Callable[[int, model.CollisionFilter], None]) -> None:
        self._send = send
        self._known: list[model.CollisionFilter] = []

    def index(self, value: Any) -> int:
        """The world's index for ``value``: a ``CollisionFilter``, an index, or None for no filter.

        A filter the service has not sent before is sent now. An int is an index
        into the world's own filters, for one added with ``physics.run``.
        """
        if value is None:
            return -1
        if isinstance(value, model.CollisionFilter):
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
    character's stand-in, a body of an instance set). ``approach`` is the
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


class ContactFilter:
    """The worker's contact filter: the application's function, given handles in place of slots.

    ``body_of(slot)`` gives the body in a world slot. The function's answer:
    True or None solves the pair, False lets the two through until they part.
    A function that raises is logged once and the pair is solved.
    """

    def __init__(self, function: Callable[[Approach], Any],
                 body_of: Callable[[Any], Body | None]) -> None:
        self.function = function
        self._body_of = body_of
        self._failed = False

    def __call__(self, pair: PairPreview) -> Verdict:
        approach = Approach(self._body_of(pair.a), self._body_of(pair.b), float(pair.approach),
                            float(pair.impulse), pair.point, pair.normal)
        try:
            answer = self.function(approach)
        except Exception:
            if not self._failed:
                self._failed = True
                log.exception('the contact filter %r failed; the pair is solved', self.function)
            return Verdict.SOLVE
        return Verdict.IGNORE_PAIR if answer is False else Verdict.SOLVE
