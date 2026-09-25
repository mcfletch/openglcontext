"""The time step a simulation advances by each frame, read from a clock.

An application that advances its own simulation from ``OnIdle`` reads a clock
once a frame and advances by the time since the last reading. Two things go
with that in every such loop, and :class:`FrameStep` holds both:

- The step is at most :attr:`FrameStep.longest` seconds. A frame held up by a
  stall, a breakpoint or a window being dragged would otherwise hand the
  simulation one step as long as the stall.
- An optional :attr:`FrameStep.cap` is the shortest frame, in seconds:
  :meth:`FrameStep.wait` says how long to wait before the next one to keep to
  it, which is how an application shows what it does at a low frame rate.

Read the clock with :func:`OpenGLContext.events.systemtime.systemTime`, which
a bounded capture puts on a fixed step per frame, so a captured run advances
the same way every time.
"""
from __future__ import annotations

from typing import Optional

__all__ = ['FrameStep']


class FrameStep:
    """Each frame's time step from a clock reading, with a longest step and a frame cap.

    ``start`` is the clock reading the first step is measured from; without
    one the first step is nought. ``longest`` and ``cap`` are in seconds.
    """

    def __init__(self, start: Optional[float] = None, longest: float = 0.1,
                 cap: Optional[float] = None) -> None:
        if not longest > 0.0:
            raise ValueError('the longest step must be above nought, not %r' % (longest,))
        #: The longest step :meth:`step` answers, in seconds.
        self.longest = float(longest)
        #: The shortest frame :meth:`wait` keeps to, in seconds; None for no cap.
        self.cap = cap
        self._last = start

    def step(self, now: float) -> float:
        """Seconds since the previous step, at most :attr:`longest`, never below nought."""
        last, self._last = self._last, float(now)
        if last is None:
            return 0.0
        return min(max(float(now) - last, 0.0), self.longest)

    def wait(self, now: float) -> float:
        """Seconds to wait before the next frame to keep to :attr:`cap`; nought without one."""
        if not self.cap or self._last is None:
            return 0.0
        return max(0.0, float(self.cap) - (float(now) - self._last))

    def toggle_cap(self, cap: float) -> Optional[float]:
        """Set :attr:`cap` to ``cap``, or lift it if one is set; return the cap now in force."""
        self.cap = None if self.cap else cap
        return self.cap
