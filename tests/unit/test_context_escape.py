"""What Escape does (:meth:`OpenGLContext.context.Context.OnEscape`).

Escape was bound straight to ``OnQuit``, which exits the process forcibly. In a
demo that is fine. In anything with state -- a game part-way through a match, a
viewer with a world loaded and a camera somewhere -- it means a key pressed to
back out of *something else* throws the whole session away, with no confirmation
and nothing to undo it.

So Escape asks the context what it means, and only the default answer is to
quit. Every program that does not override it behaves exactly as it did.
"""
import threading

from OpenGLContext import context as context_module


class _Context(context_module.Context):
    """A context with the GL and the window taken out."""

    def __init__(self):
        self.quits = 0
        self.handlers = []
        self.redrawRequest = threading.Event()

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, function))
        return function

    def OnQuit(self, event=None):
        self.quits += 1

    def suppressRedraw(self):
        pass


class TestTheDefault:
    def test_escape_quits_a_context_that_says_nothing_else(self):
        held = _Context()
        held.OnEscape()
        assert held.quits == 1

    def test_escape_is_bound_to_the_seam_not_straight_to_quitting(self):
        """Otherwise an override would be registered and never called."""
        held = _Context()
        held.setupDefaultEventCallbacks()
        bound = [fn for kind, name, fn in held.handlers
                 if name == '<escape>' and kind == 'keyboard']
        assert bound == [held.OnEscape]

    def test_it_takes_an_event_so_it_can_be_bound_directly(self):
        held = _Context()
        held.OnEscape(object())
        assert held.quits == 1


class TestOverridingIt:
    def test_a_context_may_answer_escape_some_other_way(self):
        """A game or a viewer puts a menu up instead of throwing the session away."""
        class _Paused(_Context):
            def __init__(self):
                super().__init__()
                self.paused = 0

            def OnEscape(self, event=None):
                self.paused += 1

        held = _Paused()
        held.OnEscape()
        assert held.paused == 1
        assert held.quits == 0, 'the session was thrown away anyway'
