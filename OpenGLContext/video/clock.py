"""A clock that counts frames rather than seconds.

Rendering a frame takes as long as it takes, and a recording of those frames
wants each one to be exactly one frame's worth of world later than the last. A
scene advanced against the wall clock while it is being recorded plays back
unevenly -- a frame that took 40 ms to draw is 40 ms of movement shown for
16 ms -- and a scene that streams its content in stutters exactly where the
streaming happened.

:class:`FixedStepClock` replaces the engine's time source with one that moves by
a fixed step per frame drawn, so the recording is smooth however long each frame
took, and identical between runs.

    from OpenGLContext.video.clock import FixedStepClock

    with FixedStepClock(fps=60) as clock:
        while recording:
            render()
            clock.advance()

Everything time-driven follows: TimeSensors, and so the animation they drive,
read the same source (:mod:`OpenGLContext.events.systemtime`). Code that reads
``time.time()`` directly does not, and has to be changed to
``systemtime.systemTime()`` for its motion to be recorded evenly.
"""
from __future__ import annotations

from typing import Any

from OpenGLContext.events import systemtime

__all__ = ['FixedStepClock']


class FixedStepClock:
    """Time as a function of frames finished.

    fps -- frames per second, as a number or an exact ``(numerator,
        denominator)`` pair. The pair is what keeps a long recording at 29.97
        from drifting: the step is 1001/30000 of a second, not a rounding of it.
    start -- the time the first frame happens at. By default the clock this one
        replaces is asked, so a recording continues the world's time rather than
        restarting it.

    Installed by using it as a context manager, or with :meth:`install` and
    :meth:`restore`. Nothing advances it: call :meth:`advance` once per frame
    drawn, which is where a recorder does it.
    """

    def __init__(self, fps: float | tuple[int, int] = 60,
                 start: float | None = None):
        numerator, denominator = self._as_ratio(fps)
        if numerator <= 0 or denominator <= 0:
            raise ValueError(f'frame rate must be positive, not {fps!r}')
        self.frame_rate = (numerator, denominator)
        #: Seconds one frame is worth.
        self.step = denominator / numerator
        #: Frames finished since the clock started.
        self.frames = 0
        self.start = systemtime.systemTime() if start is None else float(start)
        self._previous: Any = None
        self._installed = False

    @staticmethod
    def _as_ratio(fps: float | tuple[int, int]) -> tuple[int, int]:
        """Frame rate as an exact numerator and denominator."""
        if isinstance(fps, tuple):
            return int(fps[0]), int(fps[1])
        if abs(fps - round(fps)) < 1e-6:
            return int(round(fps)), 1
        return int(round(fps * 1001)), 1001

    def __call__(self) -> float:
        """The current time: where the frames finished so far have got to.

        Counted from the frame number rather than accumulated, so a long
        recording is exact rather than the sum of a great many small errors.
        """
        numerator, denominator = self.frame_rate
        return self.start + self.frames * denominator / numerator

    @property
    def elapsed(self) -> float:
        """Seconds of world time this clock has covered."""
        return self() - self.start

    def advance(self, frames: int = 1) -> float:
        """Finish `frames` frames, returning the new time."""
        self.frames += int(frames)
        return self()

    def install(self) -> "FixedStepClock":
        """Take over as the engine's time source."""
        if not self._installed:
            self._previous = systemtime.setTimeSource(self)
            self._installed = True
        return self

    def restore(self) -> None:
        """Give the previous time source back. Safe to call twice."""
        if self._installed:
            systemtime.setTimeSource(self._previous)
            self._installed = False
            self._previous = None

    def __enter__(self) -> "FixedStepClock":
        return self.install()

    def __exit__(self, *exception: Any) -> None:
        self.restore()

    def __repr__(self) -> str:
        return '<%s %s/%s fps, %d frames, t=%.3f>' % (
            self.__class__.__name__, self.frame_rate[0], self.frame_rate[1],
            self.frames, self())
