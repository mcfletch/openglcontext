"""Ctrl-C ends the main loop with KeyboardInterrupt, after the loop's cleanup.

A loop that returned normally would look to its caller like a closed window,
and a program run under a supervisor would exit 0.
"""

import types

import pytest

from OpenGLContext import context as context_module
from OpenGLContext.windowsystem.base import WindowSystem


class _Interrupted(WindowSystem):
    """A window system whose second pass of the loop is interrupted."""

    name = 'interrupted'

    def __init__(self, context):
        super().__init__(context)
        self.window = 'window'
        self.passes = 0
        self.released = 0

    def loopIteration(self, trace=None):
        self.passes += 1
        if self.passes == 2:
            raise KeyboardInterrupt
        return True

    def open(self, definition, parent=None):
        return True

    def release(self):
        self.released += 1

    def makeCurrent(self):
        return None

    def swap(self):
        pass

    def drawableSize(self):
        return (1, 1)


def _context():
    closed = []
    return types.SimpleNamespace(
        deferRedraw=False, loopTrace=None, closed=closed,
        closeJournals=closed.append)


class TestTheMainLoop:
    def test_the_interrupt_reaches_the_caller(self):
        windowsystem = _Interrupted(_context())
        with pytest.raises(KeyboardInterrupt):
            windowsystem.mainLoop()
        assert windowsystem.passes == 2

    def test_the_window_is_released_and_the_journals_closed_first(self):
        context = _context()
        windowsystem = _Interrupted(context)
        with pytest.raises(KeyboardInterrupt):
            windowsystem.mainLoop()
        assert windowsystem.released == 1
        assert context.closed == ['mainloop-ended']


class TestContextMainLoop:
    """The program's entry point exits with status 130 and no traceback."""

    def test_an_interrupt_exits_130(self, monkeypatch):
        class Interrupted:
            @classmethod
            def run(cls, contextClass, *args, **named):
                raise KeyboardInterrupt

        monkeypatch.setattr(context_module.Context, 'chooseWindowSystem',
                            classmethod(lambda cls, definition: 'interrupted'))
        monkeypatch.setattr(context_module._windowsystem, 'load',
                            lambda name: Interrupted)
        with pytest.raises(SystemExit) as raised:
            context_module.Context.ContextMainLoop()
        assert raised.value.code == 130
