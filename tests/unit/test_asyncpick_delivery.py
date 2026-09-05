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


class TestFlushingWhatIsInFlight:
    """``drainAsyncPicks`` delivers only what the GPU has already finished,
    which is what keeps a frame from stalling on a readback.  A caller that has
    to act on the pick before going on cannot wait an unknown number of frames
    for it, because how many it takes is a property of the machine's load.
    """

    def test_it_waits_for_every_batch(self):
        blocked = []
        mixin = _mixin([{'fence': object()}, {'fence': object()}])
        mixin._resolveBatch = (
            lambda mode, batch, block=False: blocked.append(block))
        assert mixin.flushAsyncPicks(_mode()) == 2
        assert blocked == [True, True], 'each batch is waited for, not polled'

    def test_the_queue_is_empty_afterwards(self):
        mixin = _mixin([{'fence': object()}])
        mixin._resolveBatch = lambda mode, batch, block=False: None
        mixin.flushAsyncPicks(_mode())
        assert not mixin._async_batches

    def test_nothing_in_flight_is_nothing_to_do(self):
        mixin = _mixin([])
        assert mixin.flushAsyncPicks(_mode()) == 0

    def test_a_pass_that_never_picked_is_quiet(self):
        """``_async_batches`` is None until the first pick is submitted."""
        mixin = asyncpick._AsyncPickMixin()
        assert mixin.flushAsyncPicks(_mode()) == 0

    def test_it_dispatches_through_the_pass_by_default(self):
        """The pass is the render mode, and the events go through it."""
        seen = []
        mixin = _mixin([{'fence': object()}])
        mixin._resolveBatch = (
            lambda mode, batch, block=False: seen.append(mode))
        mixin.flushAsyncPicks()
        assert seen == [mixin]
