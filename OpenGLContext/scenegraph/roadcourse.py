"""A road's centreline as something to ask about while a game runs.

:mod:`OpenGLContext.scenegraph.road` builds a road's geometry from its
centreline. A game driving on it asks the other questions: how far along the
road a car is, how far off the line, which point of the line it is beside and
which way is across the road there. :class:`RoadCourse` answers those, with no
GL and no scenegraph, so a game, a test and a headless simulation ask them the
same way.

    >>> import numpy as np
    >>> line = np.stack([np.zeros(101), np.zeros(101),
    ...                  -np.arange(101) * 10.0], axis=-1)
    >>> road = RoadCourse(line)
    >>> road.length
    1000.0
    >>> index, off = road.nearest((3.0, 0.0, -254.0))
    >>> index, off
    (25, 3.0)
    >>> road.station_of((3.0, 0.0, -254.0))
    254.0

Distances are measured across the ground (x and z), so a car in the air over
the road is still on it. :meth:`RoadCourse.nearest` searches a window of the
line around the point a caller was beside last time (``hint``) and scans the
whole line only where that answer cannot be trusted: the first question, a car
that has left the window since, or one further off the line than
``near_enough``. A :class:`Tracker` keeps that hint for one caller, so each car
on the road costs a window rather than the whole line.
"""

from __future__ import annotations

import functools
import math
from typing import Any

import numpy as np

__all__ = ['RoadCourse', 'Tracker', 'WINDOW']

#: How many points either side of the last answer a windowed search looks at.
#: A car covers under two points of a line sampled every few metres in one
#: physics step at racing speed; this is room for a frame of several steps.
WINDOW = 32


class RoadCourse:
    """Runtime queries on one road's centreline.

    ``centreline`` is (N, 3) in world units; ``closed`` says the last point
    joins the first. ``bank`` is how far the road leans at each point, as a
    fraction signed as :func:`~OpenGLContext.scenegraph.road.plan_curvature`
    is (positive leans the road's right side down), or None for a flat road.

    ``near_enough`` is the furthest off the line, in world units, that a
    windowed answer is accepted at; past it the whole line is scanned. Near
    the road the nearest point changes continuously as a car moves, so the
    window finds it; further off, another part of the road can be the nearer.
    """

    def __init__(self, centreline: Any, closed: bool = False,
                 bank: Any = None, window: int = WINDOW,
                 near_enough: float = 25.0) -> None:
        line = np.asarray(centreline, dtype='d').reshape(-1, 3)
        if len(line) < 2:
            raise ValueError('a road needs at least two points')
        self.centreline = line
        self.closed = bool(closed)
        self.bank = (np.zeros(0, dtype='d') if bank is None
                     else np.asarray(bank, dtype='d').reshape(-1))
        self.window = max(int(window), 2)
        self.near_enough = float(near_enough)

    # -- the line ----------------------------------------------------------------

    @functools.cached_property
    def stations(self) -> np.ndarray:
        """Distance along the road to each centreline point."""
        steps = np.linalg.norm(np.diff(self.centreline, axis=0), axis=1)
        found: np.ndarray = np.concatenate([[0.0], np.cumsum(steps)])
        return found

    @property
    def length(self) -> float:
        """How long the road is: to its last point, and on a closed road back
        round to its first."""
        closing = (float(np.linalg.norm(self.centreline[0]
                                        - self.centreline[-1]))
                   if self.closed else 0.0)
        return float(self.stations[-1]) + closing

    @functools.cached_property
    def segments(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Each segment on the ground: its start, its direction and length
        squared (one for a segment of no length, so nothing divides by 0)."""
        line = self.centreline[:, [0, 2]]
        if self.closed:
            starts = line
            delta = np.roll(line, -1, axis=0) - line
        else:
            starts, delta = line[:-1], line[1:] - line[:-1]
        length2 = np.einsum('ij,ij->i', delta, delta)
        return starts, delta, np.where(length2 > 0, length2, 1.0)

    def point(self, index: int) -> np.ndarray:
        """One point of the centreline, wrapping round a closed road."""
        found: np.ndarray = self.centreline[index % len(self.centreline)]
        return found

    def bank_at(self, index: int) -> float:
        """How far the road leans at that point, as a fraction; 0 where flat."""
        if not len(self.bank):
            return 0.0
        return float(self.bank[index % len(self.bank)])

    # -- where something is ------------------------------------------------------

    def nearest(self, position: Any, hint: int | None = None
                ) -> tuple[int, float]:
        """The index of the nearest centreline point, and how far off the line.

        The distance is to the line between the points rather than to the
        points themselves. The index is the nearer end of the segment the
        position is beside. ``hint`` is an index the position was near last
        time; see the module's description for when it is used.
        """
        index, off, _along = self._locate(position, hint)
        return int(round(index + _along)) % self._points, off

    def station_of(self, position: Any, hint: int | None = None) -> float:
        """How far along the road a position is, between the samples.

        From 0 up to :attr:`length`; on a closed road the start is 0 whichever
        side of it the position was measured from.
        """
        return self._station(*self._locate(position, hint))

    def _station(self, index: int, _off: float, along: float) -> float:
        _start, _delta, length2 = self.segments
        found = float(self.stations[index]
                      + along * math.sqrt(float(length2[index])))
        if self.closed and found >= self.length:
            found -= self.length
        return found

    def tracker(self) -> Tracker:
        """A caller's own view of this road, which remembers where it was."""
        return Tracker(self)

    # -- which way is across ------------------------------------------------------

    def across(self, index: int) -> np.ndarray:
        """The unit vector across the road at a point, towards its right.

        Level, then rolled by the road's lean there, so a point placed out
        from the crown follows the banked surface. Where the next point is the
        same point -- a closed road's seam written twice -- the direction is
        taken from the next point that differs.
        """
        here = self.point(index)
        for step in range(1, min(len(self.centreline), 8)):
            along = self.point(index + step) - here
            right = np.cross(along, (0.0, 1.0, 0.0))
            length = float(np.linalg.norm(right))
            if length > 1e-9:
                right = right / length
                lean = self.bank_at(index)
                if not lean:
                    return right
                along = along / max(float(np.linalg.norm(along)), 1e-9)
                angle = math.atan(lean)
                rolled: np.ndarray = (math.cos(angle) * right
                                      - math.sin(angle) * np.cross(right, along))
                return rolled
        return np.array([1.0, 0.0, 0.0])

    # -- the search ----------------------------------------------------------------

    @property
    def _points(self) -> int:
        return len(self.centreline)

    def _locate(self, position: Any, hint: int | None
                ) -> tuple[int, float, float]:
        """The segment a position is beside, how far off it, and how far
        along it as a fraction."""
        at = np.asarray(position, dtype='d').reshape(-1)[:3][[0, 2]]
        count = len(self.segments[0])
        if hint is not None and count > 2 * self.window + 1:
            chosen = (np.arange(int(hint) - self.window,
                                int(hint) + self.window + 1))
            if self.closed:
                chosen = chosen % count
            else:
                chosen = chosen[(chosen >= 0) & (chosen < count)]
            segment, off, along = self._best(at, chosen)
            # An answer on the window's edge may be the road running on past
            # it; the end of an open road is an end, not an edge.
            edges = {int(chosen[0]), int(chosen[-1])} - (
                set() if self.closed else {0, count - 1})
            if segment not in edges and off <= self.near_enough:
                return segment, off, along
        return self._best(at, np.arange(count))

    def _best(self, at: np.ndarray, chosen: np.ndarray
              ) -> tuple[int, float, float]:
        start, delta, length2 = self.segments
        start, delta, length2 = start[chosen], delta[chosen], length2[chosen]
        along = np.clip(np.einsum('ij,ij->i', at - start, delta) / length2,
                        0.0, 1.0)
        off = np.linalg.norm(start + along[:, None] * delta - at, axis=1)
        best = int(off.argmin())
        return int(chosen[best]), float(off[best]), float(along[best])


class Tracker:
    """One caller's questions about a road, answered near its last answer.

    Keep one per car: each remembers the segment its car was beside, so the
    next question searches a window there (:meth:`RoadCourse.nearest`).
    """

    def __init__(self, road: RoadCourse) -> None:
        self.road = road
        #: The segment the last answer was beside, or None before the first.
        self.hint: int | None = None

    def nearest(self, position: Any) -> tuple[int, float]:
        """:meth:`RoadCourse.nearest`, from where this caller was last."""
        index, off, along = self.road._locate(position, self.hint)
        self.hint = index
        return int(round(index + along)) % len(self.road.centreline), off

    def station_of(self, position: Any) -> float:
        """:meth:`RoadCourse.station_of`, from where this caller was last."""
        found = self.road._locate(position, self.hint)
        self.hint = found[0]
        return self.road._station(*found)

    def forget(self) -> None:
        """The caller has moved somewhere unrelated: scan the whole line."""
        self.hint = None
