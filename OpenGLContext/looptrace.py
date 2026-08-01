"""How long a whole main-loop iteration took, and which part of it took that.

:class:`~OpenGLContext.framecounter.FrameCounter` answers a narrower question
than it appears to.  It times the inside of :meth:`Context.OnDraw`, it is only
told about frames that produced a visible change, and the rate it publishes is
a **median** over a window -- deliberately outlier-proof, because a first-frame
shader compile or a synchronous model load would otherwise drag the number down
for ever.  Every one of those choices is right for "how fast is the renderer",
and every one of them hides a stutter.

A backend's loop does more than draw: it pumps the window system's events, runs
:meth:`Context.OnIdle` -- which is where an application's whole simulation
usually lives -- and waits for a redraw request.  None of that is inside the
frame counter's stopwatch.  An application can therefore crawl, visibly, at a
few updates a second while the overlay goes on reporting sixty, and no number
on the screen contradicts the other.

This module measures the other thing: **wall-clock time per loop iteration**,
split into named phases, keeping the two figures a median throws away -- the
worst iteration in the window, and how many crossed a stall threshold.  Where
the frame counter smooths, this one reports the spike, because the spike is the
complaint.

Phases nest, and a phase is charged only its **own** time: the time inside a
child phase belongs to the child.  Every phase of an iteration therefore adds
up to that iteration's wall time, so a breakdown is a division of the whole and
never an overlapping set of stopwatches that sum to more than the clock.

Configuration, both optional:

``OPENGLCONTEXT_STALL_MS``
    What counts as a stall, in milliseconds (default
    :data:`LoopTrace.DEFAULT_STALL_MS`).  Setting it also switches logging on:
    asking for a threshold is asking to be told when it is crossed.

``OPENGLCONTEXT_TRACE_STALLS``
    Log every stall's phase breakdown at ``WARNING``, keeping the default
    threshold.

Counting is always on and costs a handful of :func:`time.perf_counter` calls
per iteration.  Logging is off unless asked for, so a shipped game is silent.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

log = logging.getLogger(__name__)

__all__ = ['LoopTrace', 'describe_phases', 'STALL_MS_ENV', 'TRACE_STALLS_ENV']

STALL_MS_ENV = 'OPENGLCONTEXT_STALL_MS'
TRACE_STALLS_ENV = 'OPENGLCONTEXT_TRACE_STALLS'

Phases = Dict[str, float]
Record = Tuple[float, Phases]
#: ``(duration, phases, stalled)`` -- what :meth:`LoopTrace.subscribe` hands on.
Listener = Callable[[float, Phases, bool], None]


class LoopTrace:
    """Wall-clock cost of each main-loop iteration, divided among named phases.

    A backend drives one from its loop::

        with trace.iteration():
            with trace.phase('poll'):
                glfw.poll_events()
            with trace.phase('idle'):
                self.OnIdle()
            with trace.phase('draw'):
                self.OnDraw()

    and anything further down may open phases of its own inside those; nesting
    is what lets ``draw`` be divided into the event cascade and the render
    without either being counted twice.

    A phase opened outside an iteration is measured and discarded rather than
    refused, because ``OnDraw`` is also reached from ``drawPoll`` and from
    tests, where there is no loop to belong to.
    """

    #: Iterations kept for the median, the worst and the phase averages.  Two
    #: seconds or so of a healthy loop: long enough to be stable, short enough
    #: that the numbers still describe *now*.
    WINDOW = 120

    #: An iteration slower than this is a stall.  Twenty frames a second: past
    #: the point where a player stops calling it smooth and starts calling it
    #: broken.
    DEFAULT_STALL_MS = 50.0

    def __init__(self, window: Optional[int] = None,
                 stall_ms: Optional[float] = None,
                 trace: Optional[bool] = None,
                 clock: Any = time.perf_counter) -> None:
        self.window = int(window if window is not None else self.WINDOW)
        self.stall_seconds = (_configured_stall_ms() if stall_ms is None
                              else stall_ms) / 1000.0
        self.trace = _configured_trace() if trace is None else bool(trace)
        self._clock = clock
        self._records: List[Record] = []
        self._phases: Phases = {}
        self._stack: List[List[Any]] = []
        #: Stalls since the loop started, which outlives the window they
        #: happened in: "it hitched four times" is the report, and a window
        #: that has moved on cannot give it.
        self.stalls = 0
        #: ``(duration, phases)`` of the most recent stall, or None.
        self.last_stall: Optional[Record] = None
        self._listeners: List[Listener] = []
        # When the open iteration started, or None between iterations. Read by
        # a watcher on another thread, so it is one plain float assignment and
        # never a compound structure: a sampler must be able to read it without
        # a lock, because taking one on the main loop's hot path to find out
        # whether the main loop is slow would be its own answer.
        self._started_at: Optional[float] = None

    # -- measuring --------------------------------------------------------
    @contextmanager
    def iteration(self) -> Iterator['LoopTrace']:
        """Time one pass of the main loop, phases and all."""
        self._phases = {}
        # Cleared rather than asserted empty: an exception escaping a phase
        # unwinds through its own ``finally``, but a *backend* that forgets to
        # close one would otherwise wedge every later iteration behind a stack
        # that never empties.  A trace is diagnostic equipment; it does not get
        # to be the thing that breaks the loop.
        self._stack = []
        start = self._started_at = self._clock()
        try:
            yield self
        finally:
            self._started_at = None
            self._finish(self._clock() - start)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Charge the time spent in this block to ``name``.

        Time spent inside a *nested* phase is charged to the child instead, so
        the phases of one iteration divide its wall time rather than overlap.
        """
        stack = self._stack
        frame: List[Any] = [self._clock(), 0.0]         # started, in children
        stack.append(frame)
        try:
            yield
        finally:
            stack.pop()
            elapsed = self._clock() - frame[0]
            self._phases[name] = (self._phases.get(name, 0.0)
                                  + elapsed - frame[1])
            if stack:
                stack[-1][1] += elapsed

    def _finish(self, duration: float) -> None:
        """Close an iteration: window it, and report it if it was a stall."""
        phases = self._phases
        records = self._records
        records.append((duration, phases))
        if len(records) > self.window:
            del records[:-self.window]
        stalled = duration >= self.stall_seconds
        if stalled:
            self.stalls += 1
            self.last_stall = (duration, phases)
            if self.trace:
                log.warning('main loop stalled %.0fms: %s',
                            duration * 1000.0, describe_phases(phases))
        for listener in self._listeners:
            try:
                listener(duration, phases, stalled)
            except Exception:
                # One broken listener must not cost the frame, and must not
                # silence the others.
                log.error('loop trace listener %r failed', listener,
                          exc_info=True)

    # -- watching ---------------------------------------------------------
    def subscribe(self, listener: 'Listener') -> None:
        """Call ``listener(duration, phases, stalled)`` after every iteration.

        How a journal or a sampler learns what happened without this module
        knowing anything about files, threads or JSON.
        """
        self._listeners.append(listener)

    def iteration_age(self) -> Optional[float]:
        """Seconds the open iteration has been running, or None between them.

        For a watcher on **another thread**: a stall can only be caught while
        it is still happening, because by the time the iteration closes
        whatever was on the stack has already returned.
        """
        started = self._started_at
        if started is None:
            return None
        return float(self._clock()) - started

    def overrunning(self) -> bool:
        """Whether an iteration is open and has already outstayed the threshold.

        The cheap predicate a sampler asks before taking a sample, so a healthy
        loop is never sampled at all: a profiler that runs during the frames
        that are fine is paying for the answer it does not need, in the one
        currency the question is about.
        """
        age = self.iteration_age()
        return age is not None and age >= self.stall_seconds

    # -- reading ----------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        """The whole picture as one mapping, ready for a provider to lay out.

        ``rate`` is iterations per second of *wall clock* -- the rate the
        player's hands feel, as against the renderer's own.  ``median_ms`` is
        there to be compared with ``worst_ms``: a healthy median beside a
        tenfold worst is the signature of a loop that stutters, and the two
        numbers together say it in a way neither says alone.
        """
        records = self._records
        if not records:
            return {'iterations': 0, 'rate': 0.0, 'median_ms': 0.0,
                    'worst_ms': 0.0, 'stalls': self.stalls,
                    'stall_ms': self.stall_seconds * 1000.0}
        durations = sorted(duration for duration, _phases in records)
        total = sum(durations)
        return {
            'iterations': len(durations),
            'rate': (len(durations) / total) if total else 0.0,
            'median_ms': durations[len(durations) // 2] * 1000.0,
            'worst_ms': durations[-1] * 1000.0,
            'stalls': self.stalls,
            'stall_ms': self.stall_seconds * 1000.0,
        }

    def phases_ms(self) -> Phases:
        """Mean milliseconds per iteration spent in each phase, worst first.

        Averaged over the window and over *every* iteration in it, including
        the ones that never entered a given phase -- a draw that happens every
        other iteration should read as half its cost, not as its full cost with
        a footnote.
        """
        records = self._records
        if not records:
            return {}
        totals: Phases = {}
        for _duration, phases in records:
            for name, seconds in phases.items():
                totals[name] = totals.get(name, 0.0) + seconds
        count = len(records)
        return {name: total * 1000.0 / count
                for name, total in sorted(totals.items(),
                                          key=lambda pair: -pair[1])}

    def worst_phase(self) -> Optional[Tuple[str, float]]:
        """Where the most recent stall's time went: ``(name, ms)``, or None.

        The one row worth putting on a crowded overlay, because it turns "it
        hitched" into "it hitched *in the idle callback*", which is the whole
        of the difference between a rendering problem and a simulation one.
        """
        if self.last_stall is None:
            return None
        _duration, phases = self.last_stall
        if not phases:
            return None
        name = max(phases, key=lambda key: phases[key])
        return (name, phases[name] * 1000.0)


def describe_phases(phases: Phases) -> str:
    """A stall's phase breakdown as one line, most expensive first."""
    if not phases:
        return '-'
    return ', '.join('%s %.0fms' % (name, seconds * 1000.0)
                     for name, seconds
                     in sorted(phases.items(), key=lambda pair: -pair[1]))


def _configured_stall_ms() -> float:
    """The stall threshold the environment asks for, or the default.

    An unreadable value is the default and a warning rather than a failure: a
    mistyped diagnostic switch must not be the reason a game will not start.
    """
    asked = os.environ.get(STALL_MS_ENV)
    if not asked:
        return LoopTrace.DEFAULT_STALL_MS
    try:
        return float(asked)
    except ValueError:
        log.warning('%s=%r is not a number of milliseconds; using %s',
                    STALL_MS_ENV, asked, LoopTrace.DEFAULT_STALL_MS)
        return LoopTrace.DEFAULT_STALL_MS


def _configured_trace() -> bool:
    """Whether stalls should be logged as well as counted."""
    return bool(os.environ.get(TRACE_STALLS_ENV)
                or os.environ.get(STALL_MS_ENV))
