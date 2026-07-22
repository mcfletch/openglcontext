"""HasMouseMoveHandlers reached into pydispatch internals and
rescanned the whole global registry per event type. The dispatcher lookup now
lives on the EventManager (`hasReceivers`), and the context asks the relevant
managers instead of walking the registry itself.
"""
import pytest

from OpenGLContext.events.eventmanager import EventManager


class _MoveManager(EventManager):
    type = 'mousemove'


def _receiver(**named):
    return None


class TestManagerHasReceivers:
    def test_false_with_no_callbacks(self):
        assert _MoveManager().hasReceivers() is False

    def test_true_after_register_false_after_remove(self):
        m = _MoveManager()
        _MoveManager.registerCallback(key='k', function=_receiver)
        try:
            assert m.hasReceivers() is True
        finally:
            _MoveManager.registerCallback(key='k', function=None)  # deregister
        assert m.hasReceivers() is False

    def test_ignores_other_event_types(self):
        class _Other(EventManager):
            type = 'keypress'
        _Other.registerCallback(key='x', function=_receiver)
        try:
            assert _MoveManager().hasReceivers() is False
        finally:
            _Other.registerCallback(key='x', function=None)


class TestHasMouseMoveHandlersDelegates:
    def _ctx(self, managers):
        from OpenGLContext.context import Context

        class Fake:
            def getEventManager(self, t):
                return managers.get(t)
        f = Fake()
        f.hasMouseMoveHandlers = Context.hasMouseMoveHandlers.__get__(f)
        return f

    def test_true_when_a_manager_reports_receivers(self):
        class Yes:
            def hasReceivers(self):
                return True
        ctx = self._ctx({'mousein': Yes()})
        assert ctx.hasMouseMoveHandlers() is True

    def test_false_when_no_manager_reports(self):
        class No:
            def hasReceivers(self):
                return False
        ctx = self._ctx({'mousemove': No(), 'mousein': No(), 'mouseout': None})
        assert ctx.hasMouseMoveHandlers() is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
