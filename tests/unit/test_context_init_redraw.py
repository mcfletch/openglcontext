"""A redraw asked for while a context is still starting up
(:meth:`OpenGLContext.context.Context.DoInit`).

``triggerRedraw(1)`` means "draw now if you can", and during ``OnInit`` a
context *can*: it is on the context thread and it is not drawing.  So it did --
re-entering ``OnDraw`` in the middle of initialisation, against a scenegraph
that did not exist yet, and then blocking in the buffer swap.

Anything that asks is ordinary code: ``ScreenMixin.addHUDLayer`` requests a
frame, and adding a HUD in ``OnInit`` is exactly what the documentation tells an
application to do.  So the fix belongs here rather than in each caller: requests
made during start-up are remembered and satisfied by the first real frame.
"""
from OpenGLContext import context as context_module


class _Context(context_module.Context):
    """A context with the GL and the window taken out.

    ``Context.__init__`` builds a window; this stands in for one that has
    already been built and is about to be initialised.
    """

    def __init__(self, work):
        import threading
        self.drawn = 0
        self.work = work
        self.currentDepth = 0
        self.redrawRequest = threading.Event()

    def setCurrent(self):
        pass

    def unsetCurrent(self):
        pass

    def OnInit(self):
        self.work(self)

    def OnDraw(self, *args, **named):
        self.drawn += 1
        return 1


def _stayOnThisThread(monkeypatch):
    """``triggerRedraw`` only draws on the context thread; say we are on it."""
    monkeypatch.setattr(context_module, 'inContextThread', lambda: True)


class TestARedrawAskedForDuringStartUp:
    def test_it_does_not_draw_before_initialisation_has_finished(self, monkeypatch):
        _stayOnThisThread(monkeypatch)
        held = _Context(lambda self: self.triggerRedraw(1))
        held.DoInit()
        assert held.drawn == 0, 'drew against a half-built context'

    def test_the_request_is_remembered_rather_than_dropped(self, monkeypatch):
        """The first real frame still happens; it is only deferred."""
        _stayOnThisThread(monkeypatch)
        held = _Context(lambda self: self.triggerRedraw(1))
        held.DoInit()
        assert held.shouldRedraw() is True

    def test_deferral_ends_with_initialisation(self, monkeypatch):
        _stayOnThisThread(monkeypatch)
        held = _Context(lambda self: None)
        held.DoInit()
        held.triggerRedraw(1)
        assert held.drawn == 1

    def test_deferral_ends_even_if_initialisation_fails(self, monkeypatch):
        """A context that failed to start must still be able to draw a message."""
        _stayOnThisThread(monkeypatch)

        def explode(self):
            raise RuntimeError('no model')
        held = _Context(explode)
        try:
            held.DoInit()
        except RuntimeError:
            pass
        assert held.deferRedraw is False

    def test_a_context_that_asks_for_nothing_draws_nothing(self, monkeypatch):
        _stayOnThisThread(monkeypatch)
        held = _Context(lambda self: None)
        held.DoInit()
        assert held.drawn == 0
