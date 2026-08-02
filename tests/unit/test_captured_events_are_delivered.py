"""A captured event type has someone listening, by definition.

The selection pass drops mouse-move events when nothing is registered for them,
which is a real saving -- most frames have no use for them at all. It asks
``Context.hasMouseMoveHandlers``, which asks each event manager whether the
dispatcher has live receivers for it.

**A capture registers nothing with the dispatcher.**
``EventHandlerMixin.captureEvents`` swaps the manager in the slot instead, which
is how a drag takes over an event type for its duration -- so during a
right-drag the slot holds an ``ExamineManager``, the dispatcher holds nothing
for ``mousemove``, the check says nobody is listening, and every move the drag
exists to consume is filtered away before it arrives. Examine mode started and
then never saw a single movement.
"""
import pytest

from OpenGLContext.events import eventmanager
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin


class _Manager(eventmanager.EventManager):
    """A manager that takes an event type over for the duration of a drag."""

    type = 'examine'

    def ProcessEvent(self, event):
        return True


class _Host(EventHandlerMixin):
    """The little of a context this needs: real managers, no window."""

    def __init__(self):
        self.initializeEventManagers()


@pytest.fixture
def host():
    from OpenGLContext.interactivecontext import InteractiveContext
    _Host.EventManagerClasses = InteractiveContext.EventManagerClasses
    return _Host()


class TestKnowingSomethingIsCaptured:
    def test_nothing_is_captured_to_begin_with(self, host):
        assert host.isCapturingEvents('mousemove') is False

    def test_a_capture_is_visible(self, host):
        host.captureEvents('mousemove', _Manager())
        assert host.isCapturingEvents('mousemove') is True

    def test_releasing_it_is_visible_too(self, host):
        host.captureEvents('mousemove', _Manager())
        host.captureEvents('mousemove', None)
        assert host.isCapturingEvents('mousemove') is False

    def test_capturing_one_type_says_nothing_about_another(self, host):
        host.captureEvents('mousemove', _Manager())
        assert host.isCapturingEvents('mousebutton') is False

    def test_an_unknown_type_is_not_captured(self, host):
        assert host.isCapturingEvents('nonsense') is False


class TestMovesAreDeliveredWhileCaptured:
    """The whole point: the pass must not filter away what a drag is waiting for."""

    def _context(self):
        from OpenGLContext.context import Context

        class _Probe(_Host):
            getEventManager = EventHandlerMixin.getEventManager
            hasMouseMoveHandlers = Context.hasMouseMoveHandlers
        from OpenGLContext.interactivecontext import InteractiveContext
        _Probe.EventManagerClasses = InteractiveContext.EventManagerClasses
        return _Probe()

    def test_nobody_listening_means_moves_can_be_dropped(self):
        assert self._context().hasMouseMoveHandlers() is False

    def test_a_drag_that_captured_moves_is_listening(self):
        probe = self._context()
        probe.captureEvents('mousemove', _Manager())
        assert probe.hasMouseMoveHandlers() is True

    def test_and_stops_being_so_when_the_drag_ends(self):
        probe = self._context()
        probe.captureEvents('mousemove', _Manager())
        probe.captureEvents('mousemove', None)
        assert probe.hasMouseMoveHandlers() is False

    def test_capturing_mousein_counts_as_well(self):
        """The check covers three types; a capture of any of them is a listener."""
        probe = self._context()
        probe.captureEvents('mousein', _Manager())
        assert probe.hasMouseMoveHandlers() is True


class TestTheExamineDragItself:
    """``ExamineManager`` is what captures, and what was being starved."""

    def test_it_captures_the_moves_it_needs(self):
        import inspect
        from OpenGLContext.move import examinemanager
        source = inspect.getsource(examinemanager.ExamineManager.OnBind)
        assert "captureEvents" in source
        assert "mousemove" in source

    def test_its_own_type_is_not_the_type_it_captures(self):
        """Which is exactly why asking it for receivers answered nothing."""
        from OpenGLContext.move.examinemanager import ExamineManager
        assert ExamineManager.type == 'examine'
