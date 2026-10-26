"""Things stepped once a frame, and calls made after a delay, on one frame clock.

A rigged model's clips advance when ``model.update(dt)`` is called, and a game
that waits a few seconds before doing something counts the seconds itself.
:class:`Animations` does both for a context, which holds one as the target of
:meth:`~OpenGLContext.context.Context.animate` and
:meth:`~OpenGLContext.context.Context.after`::

    self.animate(model)                       # model.update(dt) every frame
    self.after(15.0, self.choose_a_goal)      # one call, fifteen seconds on

:meth:`Animations.frame` takes a clock reading, works out the step with a
:class:`~OpenGLContext.events.framestep.FrameStep` and gives it to everything
added. A delay counts those steps, so a paused or stalled frame clock delays
it by the same amount, and a capture on a fixed clock makes it on the same
frame every run. The object holds no GL and reads no clock of its own.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from OpenGLContext.events.framestep import FrameStep

__all__ = ['Animated', 'Animations']


class Animated:
    """One thing :class:`Animations` steps or one call it waits to make; :meth:`stop` ends it."""

    __slots__ = ('_owner', 'function', 'remaining')

    def __init__(self, owner: Animations, function: Callable[..., Any],
                 remaining: float | None) -> None:
        self._owner: Animations | None = owner
        #: Called with each step, or with nothing once a delay is over.
        self.function = function
        #: Seconds left before a delayed call; None for a thing stepped every frame.
        self.remaining = remaining

    @property
    def running(self) -> bool:
        """Whether the thing is still stepped, or the call still waiting."""
        return self._owner is not None

    def stop(self) -> None:
        """Stop stepping the thing, or cancel the call. Stopping twice is harmless."""
        owner, self._owner = self._owner, None
        if owner is not None:
            owner._forget(self)


class Animations:
    """What a context steps each frame, and the calls it makes after a delay.

    ``longest`` is the longest step in seconds, so a frame held up by a stall
    gives no animation a jump.
    """

    def __init__(self, longest: float = 0.1) -> None:
        self._steps = FrameStep(longest=longest)
        self._running: list[Animated] = []

    def __len__(self) -> int:
        return len(self._running)

    def animate(self, thing: Any) -> Animated:
        """Step ``thing`` each frame: ``thing.update(dt)``, or ``thing(dt)`` for a function.

        Returns the :class:`Animated` whose :meth:`~Animated.stop` ends it. A
        thing added while a frame steps the others is first stepped on the next.
        """
        update = getattr(thing, 'update', None)
        function = update if callable(update) else thing
        if not callable(function):
            raise TypeError('animate takes an object with update(dt) or a function of dt, '
                            'not %r' % (thing,))
        handle = Animated(self, function, None)
        self._running.append(handle)
        return handle

    def after(self, seconds: float, function: Callable[[], Any]) -> Animated:
        """Call ``function()`` once ``seconds`` of frame steps have passed."""
        if not seconds >= 0.0:
            raise ValueError('a delay is a time from now, not %r' % (seconds,))
        handle = Animated(self, function, float(seconds))
        self._running.append(handle)
        return handle

    def frame(self, now: float) -> bool:
        """Step everything by the time since the last frame; whether anything is still running.

        ``now`` is a clock reading in seconds. The first frame steps by nought.
        """
        dt = self._steps.step(now)
        for handle in list(self._running):
            if not handle.running:
                continue
            if handle.remaining is None:
                handle.function(dt)
                continue
            handle.remaining -= dt
            if handle.remaining <= 1e-9:
                handle.stop()
                handle.function()
        return bool(self._running)

    def _forget(self, handle: Animated) -> None:
        if handle in self._running:
            self._running.remove(handle)
