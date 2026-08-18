"""The "real world" time signature the engine advances everything against.

Every time-driven node reads this clock: a :class:`~OpenGLContext.events.timer.Timer`
polled without a time of its own takes one from here, and so do the TimeSensors
that drive the animation in a scenegraph. One source, so nothing in a scene can
drift away from anything else in it.

The source is replaceable, which is what a recording needs. Rendering a frame
takes as long as it takes, and a video wants each frame to be exactly one
frame's worth of world later than the last, so a recorder installs a clock that
advances by a fixed step per frame drawn and the whole scene follows it. It is
the same mechanism a deterministic replay or a debugger's frame-step would want.

Note:
    This is wall-clock, not CPU time.
"""
import time

__all__ = ['systemTime', 'setTimeSource', 'timeSource', 'wallClock']


def wallClock():
    """The default source: real time, as it passes."""
    return time.time()


_source = wallClock


def systemTime():
    """Generate a "real-world" time value"""
    return _source()


def timeSource():
    """The source :func:`systemTime` is currently reading."""
    return _source


def setTimeSource(source):
    """Install `source` as the clock, returning the one it replaced.

    source -- a callable of no arguments returning seconds as a float, or None
        to go back to the wall clock

    Keep the returned source and put it back when finished, so whatever
    installed a clock before this one is not left displaced::

        previous = setTimeSource(myClock)
        try:
            ...
        finally:
            setTimeSource(previous)

    A source should never go backwards: a timer handed a time earlier than the
    last one it saw will report negative progress.
    """
    global _source
    previous = _source
    _source = wallClock if source is None else source
    return previous
