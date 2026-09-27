"""A changing reason, kept as the stretches of a run over which each one held.

Something asked every step why it is as it is -- why a driver has not
overtaken, why a character is not moving -- answers a reason each step, and
the reasons flicker at a boundary between two of them.  :class:`Stretch`
turns that into what a journal wants: one :class:`Held` per stretch that
lasted, with the reasons that interrupted it too briefly to count named
inside it.  No GL, and no clock of its own: the caller says how long each step
was.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ['Held', 'Stretch']


@dataclass
class Held:
    """One reason that held over a stretch of a run."""

    why: str
    #: Where it began, in whatever the caller measures by: a station along a
    #: course, a time, a frame; 0.0 where it names none.
    at: float = 0.0
    seconds: float = 0.0
    #: What was written down about it when it began.
    fields: dict[str, Any] = field(default_factory=dict)
    #: Other reasons that came and went inside it without holding.
    also: set[str] = field(default_factory=set)


class Stretch:
    """The reason something is so, kept as stretches of a run.

    :meth:`hold` is told the reason that holds on each step. A different reason
    starts a new stretch only once it has held for ``holds`` seconds; one that
    goes back sooner is folded into the stretch it interrupted, its time counted
    there and its name kept in :attr:`Held.also`. So something sitting on the
    boundary between two reasons is one stretch with both named, and a stretch
    shorter than ``holds`` is not one at all.

        >>> wanting = Stretch(holds=0.2)
        >>> for _ in range(30):
        ...     _ = wanting.hold('too close', 0.05, at=100.0)
        ...     _ = wanting.hold('lane not clear', 0.05, at=100.0)
        >>> done = wanting.end()
        >>> done.why, round(done.seconds, 1), sorted(done.also)
        ('too close', 3.0, ['lane not clear'])
    """

    def __init__(self, holds: float) -> None:
        self.holds = float(holds)
        #: The stretch under way, or None.
        self.open: Held | None = None
        self._next: Held | None = None
        self._announced = False

    def hold(self, why: str, dt: float, at: float = 0.0,
             **fields: Any) -> Held | None:
        """``why`` held for ``dt`` more seconds, beginning at ``at``.

        Returns the stretch this ended, where it lasted long enough to be one.
        ``at`` and ``fields`` are kept only by the step that begins a stretch.
        """
        dt = max(float(dt), 0.0)
        if self.open is None:
            self.open = Held(why, float(at), fields=dict(fields))
        if why == self.open.why:
            self._fold()
            self.open.seconds += dt
            return None
        if self._next is None or self._next.why != why:
            self._fold()
            self._next = Held(why, float(at), fields=dict(fields))
        self._next.seconds += dt
        if self._next.seconds < self.holds:
            return None
        done, self.open, self._next = self.open, self._next, None
        self._announced = False
        return done if done.seconds >= self.holds else None

    def end(self) -> Held | None:
        """Close the stretch under way; returns it if it lasted long enough."""
        self._fold()
        done, self.open, self._announced = self.open, None, False
        return done if done is not None and done.seconds >= self.holds else None

    def announce(self) -> bool:
        """True once for each stretch, the first time it is asked after the
        stretch has held for ``holds`` seconds."""
        if self._announced or self.open is None \
                or self.open.seconds < self.holds:
            return False
        self._announced = True
        return True

    def _fold(self) -> None:
        """A reason that went back before it held joins the open stretch."""
        if self._next is not None and self.open is not None:
            self.open.seconds += self._next.seconds
            self.open.also.add(self._next.why)
        self._next = None
