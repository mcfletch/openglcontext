"""Turning a stream of wheel reports into whole notches.

A mouse wheel reaches an application as an *amount of rotation* on most
toolkits, and the rest of OpenGLContext reads a wheel as the press and release
of a button no physical mouse has (see
:data:`OpenGLContext.events.mouseevents.WHEEL_UP`).  The conversion is the same
wherever the toolkit states how much rotation one detent is: Qt reports eighths
of a degree and calls fifteen degrees a notch, wxPython names its own delta.

**A wheel and a touchpad are different devices reported the same way.**  A wheel
sends a whole detent at a time and leaves nothing over; a high-resolution wheel
or a touchpad sends a stream of fractions, which are summed so that a slow drag
scrolls once it has asked for a whole notch and a fast one scrolls no further
than it was pushed.

:mod:`OpenGLContext.events.glfwevents` does *not* use this: GLFW states no
detent size and the platforms disagree about it, so that backend has to learn
the size from what arrives.
"""

from __future__ import annotations

from typing import List

from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP

__all__ = ['WheelNotches']


class WheelNotches(object):
    """The whole notches in a stream of wheel reports, carrying the remainder

    One per window: the carried fraction is a property of the device the user
    is turning, not of any single event.
    """

    def __init__(self, detent: float) -> None:
        """detent -- how much rotation the toolkit reports for one notch"""
        self.detent = float(detent)
        #: Rotation reported so far that has not yet made a whole notch.
        self.remainder = 0.0

    def notches(self, rotation: float) -> List[int]:
        """The wheel buttons one report of ``rotation`` amounts to

        Answers a list of :data:`~OpenGLContext.events.mouseevents.WHEEL_UP` or
        :data:`~OpenGLContext.events.mouseevents.WHEEL_DOWN`, one per notch, in
        the order they happened -- which is to say all the same, since a single
        report only goes one way.

        Turning back drops what was carried, so jitter over a touchpad cannot
        accumulate into a notch in the direction it is not moving.
        """
        rotation = float(rotation)
        if not rotation or not self.detent:
            return []
        carried = self.remainder
        if (carried > 0.0) != (rotation > 0.0):
            carried = 0.0
        total = carried + rotation
        whole = int(total / self.detent)
        self.remainder = total - whole * self.detent
        return [WHEEL_UP if total > 0.0 else WHEEL_DOWN] * abs(whole)
