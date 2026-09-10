"""Releasing a capture that was never taken must leave the slot alone.

``captureEvents`` swaps a manager into the dispatch slot for the duration of a
drag and puts the original back when the drag ends.  The release is the half
that is easy to reach twice -- a drag ended by the button coming up and again by
the mode being unbound -- and a release with no capture behind it must not empty
the slot, because a context whose ``mousemove`` slot holds ``None`` has no mouse
movement at all for the rest of the session.
"""

import pytest

from OpenGLContext.events import eventmanager
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin


class _Drag(eventmanager.EventManager):
    """A manager standing in for the one a drag captures with."""

    type = 'examine'


class _Host(EventHandlerMixin):
    """The little of a context this needs: real managers, no window."""

    def __init__(self):
        self.initializeEventManagers()


@pytest.fixture
def host():
    from OpenGLContext.interactivecontext import InteractiveContext
    _Host.EventManagerClasses = InteractiveContext.EventManagerClasses
    return _Host()


def test_a_release_with_no_capture_keeps_the_manager(host):
    before = host.getEventManager('mousemove')
    assert before is not None
    host.captureEvents('mousemove', None)
    assert host.getEventManager('mousemove') is before


def test_releasing_twice_keeps_the_manager(host):
    before = host.getEventManager('mousemove')
    host.captureEvents('mousemove', _Drag())
    host.captureEvents('mousemove', None)
    host.captureEvents('mousemove', None)
    assert host.getEventManager('mousemove') is before


def test_a_capture_over_an_empty_slot_is_released_cleanly(host):
    """Nothing was in the slot, so nothing is put back -- and the capture ends.

    The record of what to restore is ``None`` here, which is the same value a
    slot that was never captured has; telling the two apart is what keeps
    ``isCapturingEvents`` truthful.
    """
    assert host.getEventManager('examine') is None
    host.captureEvents('examine', _Drag())
    assert host.isCapturingEvents('examine') is True
    host.captureEvents('examine', None)
    assert host.isCapturingEvents('examine') is False
    assert host.getEventManager('examine') is None
