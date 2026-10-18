"""Holding a subsystem's cost to how it grows with the size of the scene.

A frame's cost is set by what the scene holds, and a game's scene holds more
than a demo's. Work that grows faster than the scene -- every object against
every zone, every record for every mirror view -- is fast in a small test and
the whole frame in a large world. :func:`check_scaling` measures one piece of
work at ``n`` objects and at ``factor * n``, and fails when the second costs
more than ``most`` times the first::

    from OpenGLContext.testing.scaling import check_scaling

    @pytest.mark.serial
    def test_classifying_grows_with_the_objects():
        def prepare(n):
            table, boxes = street(rooms=n // 100, objects=n)
            return lambda: table.classify_many(*boxes)
        check_scaling(prepare, n=2000, most=6.0)

``prepare(n)`` builds the scene at size ``n`` and returns the work, a
callable taking no arguments. The work is run once before it is measured, so
what is measured is the steady cost rather than the first call's setup.

Two measures:

``'time'``
    The work's wall-clock time, the least of ``repeat`` runs, the two
    sizes timed in turn so that both see the same load. A clock
    measures the machine as well as the code, so a test measuring time
    carries the ``serial`` marker and runs with the machine to itself; the
    plugin's ``check_scaling`` fixture refuses a test without it.
``'count'``
    The number the work returns: how many objects it touched, how many
    records it built. A count is the same on every machine, so it needs no
    marker, and is the better measure where the work can report one.

Linear work at ``factor`` 4 costs about 4 times as much; work that does not
depend on the scene's size costs about the same; work that grows as the
square costs about 16 times. ``most`` is set between the growth the work
should have and the next one up, with room for the noise a clock has.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal

__all__ = ['Scaling', 'ScalingExceeded', 'check_scaling', 'measure_scaling']

Measure = Literal['time', 'count']


class ScalingExceeded(AssertionError):
    """Work grew with the scene faster than the bound a test gave it."""


@dataclass(frozen=True)
class Scaling:
    """What the work cost at each size.

    ``sizes`` is ``(n, factor * n)``, ``costs`` the work's cost at each (in
    seconds for ``'time'``, as returned for ``'count'``), and ``ratio`` the
    second over the first.
    """

    sizes: tuple[int, int]
    costs: tuple[float, float]
    measure: Measure

    @property
    def ratio(self) -> float:
        small, large = self.costs
        if small <= 0:
            return 1.0 if large <= 0 else float('inf')
        return large / small

    def __str__(self) -> str:
        unit = ' s' if self.measure == 'time' else ''
        return ('%d objects cost %.6g%s and %d cost %.6g%s: %.2f times as much'
                % (self.sizes[0], self.costs[0], unit, self.sizes[1],
                   self.costs[1], unit, self.ratio))


def _counts(works: list[Callable[[], Any]]) -> list[float]:
    """What each work returns on its second run."""
    found = []
    for work in works:
        work()
        found.append(float(work()))
    return found


def _times(works: list[Callable[[], Any]], repeat: int) -> list[float]:
    """The least of ``repeat`` wall-clock times for each work, the works timed in turn.

    Taking the sizes in turn rather than one after the other puts both through
    the same stretch of whatever else the machine is doing.
    """
    for work in works:
        work()
    best = [float('inf')] * len(works)
    for _ in range(repeat):
        for index, work in enumerate(works):
            started = time.perf_counter()
            work()
            best[index] = min(best[index], time.perf_counter() - started)
    return best


def measure_scaling(prepare: Callable[[int], Callable[[], Any]], *, n: int,
                    factor: int = 4, measure: Measure = 'time',
                    repeat: int = 5) -> Scaling:
    """The work's cost at ``n`` and at ``factor * n``, measured and not judged."""
    if measure not in ('time', 'count'):
        raise ValueError('measure is %r; it is "time" or "count"' % (measure,))
    if n < 1 or factor < 2:
        raise ValueError('scaling needs n of 1 or more and a factor of 2 or '
                         'more, not n=%r, factor=%r' % (n, factor))
    sizes = (n, n * factor)
    works = [prepare(size) for size in sizes]
    costs = _counts(works) if measure == 'count' else _times(works, repeat)
    return Scaling(sizes, (costs[0], costs[1]), measure)


def check_scaling(prepare: Callable[[int], Callable[[], Any]], *, n: int,
                  most: float, factor: int = 4, measure: Measure = 'time',
                  repeat: int = 5) -> Scaling:
    """The :class:`Scaling` of the work; raise where it grew more than ``most`` times.

    Raises :class:`ScalingExceeded` when the cost at ``factor * n`` is more
    than ``most`` times the cost at ``n``.
    """
    found = measure_scaling(prepare, n=n, factor=factor, measure=measure,
                            repeat=repeat)
    if found.ratio > most:
        raise ScalingExceeded('%s; the bound is %.2f times' % (found, most))
    return found
