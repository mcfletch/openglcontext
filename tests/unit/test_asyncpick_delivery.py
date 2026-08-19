"""A pick in flight keeps asking for the frame it is delivered on.

An asynchronous pick is read into a fenced buffer during one render and
dispatched by :meth:`drainAsyncPicks` during a *later* one. An application that
renders only when something changed -- an editor, a viewer, anything not
animating -- has nothing to change while the batch is in flight, so without a
request of its own the batch waits for whatever unrelated event next asks for a
frame. The click is then delivered seconds later, when the pointer happens to
move, and the menu it opened appears then.
"""
import types

import pytest

from OpenGLContext.passes import asyncpick


class RecordingContext:
    """As much of a context as the pick mixin asks anything of."""

    def __init__(self):
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


def _mode():
    return types.SimpleNamespace(context=RecordingContext())


def _mixin(batches):
    mixin = asyncpick._AsyncPickMixin()
    mixin._async_batches = list(batches)
    return mixin


class TestDrainAsksForAnotherFrame:
    def test_an_unsignalled_batch_asks_for_a_frame(self, monkeypatch):
        """The fence has not signalled, so the batch needs another render."""
        monkeypatch.setattr(asyncpick, 'glClientWaitSync',
                            lambda fence, flags, timeout: 0)
        mixin = _mixin([{'fence': object()}])
        mode = _mode()
        mixin.drainAsyncPicks(mode)
        assert mixin._async_batches, "the batch should still be in flight"
        assert mode.context.redraws == 1

    def test_a_resolved_batch_asks_for_nothing(self, monkeypatch):
        """Nothing is left in flight, so the loop is free to go quiet."""
        monkeypatch.setattr(asyncpick, 'glClientWaitSync',
                            lambda fence, flags, timeout: asyncpick.GL_ALREADY_SIGNALED)
        resolved = []
        mixin = _mixin([{'fence': object()}])
        mixin._resolveBatch = lambda mode, batch, block=False: resolved.append(batch)
        mode = _mode()
        mixin.drainAsyncPicks(mode)
        assert resolved and not mixin._async_batches
        assert mode.context.redraws == 0

    def test_an_empty_queue_asks_for_nothing(self):
        """No picks at all: an idle loop stays idle."""
        mixin = _mixin([])
        mode = _mode()
        mixin.drainAsyncPicks(mode)
        assert mode.context.redraws == 0
