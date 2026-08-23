"""Tests for :class:`_AsyncPickMixin` -- the async PBO/fence pick readback.

``_dispatchPickEvent`` is pure and exercised without GL. The PBO pooling, fence
submit/drain and batch resolve drive core-profile GL, so they run against a real
:class:`SelectionBufferFBO` rendered in a hidden GLFW window; a bare
``SelectionMixin`` instance supplies the ``matrix``/``projection``/``viewport``
and selection-buffer hooks the mixin expects. Skips cleanly with no GL context.
"""

import numpy as np
import pytest


from OpenGL.GL import (  # noqa: E402
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT, glClear, glClearColor, glDrawBuffers, glFinish, glViewport,
)

from OpenGLContext.passes import asyncpick  # noqa: E402
from OpenGLContext.passes.selection import SelectionMixin  # noqa: E402
from OpenGLContext.passes.selectionbuffers import SelectionBufferFBO  # noqa: E402


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeEvent:
    type = 'mousebutton'

    def __init__(self, x, y):
        self._p = (x, y)
        self.paths = None
        self.viewCoordinate = None
        self.modelViewMatrix = None
        self.projectionMatrix = None
        self.viewport = None

    def getPickPoint(self):
        return self._p

    def setObjectPaths(self, paths):
        self.paths = paths


class FakeContext:
    def __init__(self):
        self.processed = []

    def ProcessEvent(self, event):
        self.processed.append(event)


class FakeMode:
    def __init__(self):
        self.context = FakeContext()


def _bare():
    sel = SelectionMixin.__new__(SelectionMixin)
    sel.matrix = np.identity(4, 'f')
    # The camera model-view the picks unproject against. The real pass
    # sets both in setViewPlatform; sel.matrix is then rewritten per node
    # by the traversal, which is why the dispatch reads this one.
    sel.modelView = np.identity(4, 'f')
    sel.projection = np.identity(4, 'f')
    sel.viewport = (0, 0, 16, 16)
    sel._async_batches = None
    sel._pbo_free = None
    return sel


ENCODED_ID = 1 | (2 << 8) | (3 << 16)   # rgba bytes (1, 2, 3, 0)


def _buffer_with_id(size=16):
    """A rendered MRT buffer whose whole id attachment holds ENCODED_ID."""
    sb = SelectionBufferFBO()
    assert sb.ensure_size(size, size)
    sb.bind()
    glViewport(0, 0, size, size)
    glClearColor(0, 0, 0, 0)
    glClear(GL_DEPTH_BUFFER_BIT)
    glDrawBuffers(1, [GL_COLOR_ATTACHMENT1])
    glClearColor(1 / 255.0, 2 / 255.0, 3 / 255.0, 0.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])
    sb.unbind()
    return sb


def _attach_buffer(sel, sb):
    sel._selection_buffer = sb
    sel._getSelectionBuffer = lambda: sb


# --------------------------------------------------------------------------- #
# _dispatchPickEvent (pure, no GL)
# --------------------------------------------------------------------------- #
class TestDispatchPickEvent:
    def test_populates_event_and_forwards_to_context(self):
        mode = FakeMode()
        ev = FakeEvent(3, 4)
        mv, proj, vp = object(), object(), (0, 0, 10, 10)
        SelectionMixin._dispatchPickEvent(
            mode, ev, [['node']], 3, 4, 0.5, mv, proj, vp)
        assert ev.paths == [['node']]
        assert ev.viewCoordinate == (3, 4, 0.5)
        assert ev.modelViewMatrix is mv
        assert ev.projectionMatrix is proj
        assert ev.viewport is vp
        assert mode.context.processed == [ev]

    def test_no_processevent_method_is_tolerated(self):
        class NoProc:
            pass

        class Mode:
            context = NoProc()
        ev = FakeEvent(0, 0)
        SelectionMixin._dispatchPickEvent(
            Mode(), ev, [[]], 0, 0, 1.0, None, None, None)
        # Still fully populated even though the context can't receive it.
        assert ev.paths == [[]]
        assert ev.viewCoordinate == (0, 0, 1.0)


# --------------------------------------------------------------------------- #
# PBO pooling
# --------------------------------------------------------------------------- #
class TestPBOPool:
    def test_release_then_acquire_reuses_buffer(self, gl_context):
        sel = _bare()
        pid, cap = sel._acquirePBO(16)
        assert cap >= 256                      # rounded up to a floor
        sel._releasePBO(pid, cap)
        pid2, cap2 = sel._acquirePBO(16)       # fits -> same buffer back
        assert pid2 == pid and cap2 == cap

    def test_acquire_creates_new_when_pool_too_small(self, gl_context):
        sel = _bare()
        small_pid, small_cap = sel._acquirePBO(16)
        sel._releasePBO(small_pid, small_cap)
        big_pid, big_cap = sel._acquirePBO(4096)   # pooled one too small
        assert big_pid != small_pid
        assert big_cap >= 4096

    def test_release_initializes_pool(self, gl_context):
        sel = _bare()
        sel._pbo_free = None
        sel._releasePBO(123, 256)
        assert sel._pbo_free == [(123, 256)]


# --------------------------------------------------------------------------- #
# submit / drain / resolve
# --------------------------------------------------------------------------- #
class TestAsyncSubmitDrain:
    def test_empty_events_is_noop(self, gl_context):
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        sel.submitAsyncPicks(FakeMode(), {}, {})
        assert sel._async_batches is None

    def test_uninitialized_buffer_skips_submit(self, gl_context):
        sel = _bare()
        _attach_buffer(sel, SelectionBufferFBO())    # never ensure_size'd
        sel.submitAsyncPicks(FakeMode(), {'k': FakeEvent(8, 8)}, {})
        assert sel._async_batches is None

    def test_drain_with_no_batches_is_noop(self, gl_context):
        sel = _bare()
        sel.submitAsyncPicks  # noqa: B018  (attribute exists)
        sel.drainAsyncPicks(FakeMode())            # _async_batches is None
        assert sel._async_batches is None

    def test_inbounds_pick_resolves_to_mapped_path(self, gl_context):
        sel = _bare()
        sb = _buffer_with_id()
        _attach_buffer(sel, sb)
        path = ['transform', 'shape']
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.submitAsyncPicks(mode, {'k': ev}, {ENCODED_ID: path})
        assert len(sel._async_batches) == 1
        glFinish()                                 # make the fence signal
        sel.drainAsyncPicks(mode)
        assert sel._async_batches == []            # drained
        assert ev.paths == [path]
        assert ev.viewCoordinate[0] == 8 and ev.viewCoordinate[1] == 8
        assert mode.context.processed == [ev]

    def test_out_of_bounds_pick_resolves_empty(self, gl_context):
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        mode = FakeMode()
        ev = FakeEvent(-4, -4)                      # outside the 16x16 buffer
        sel.submitAsyncPicks(mode, {'k': ev}, {ENCODED_ID: ['x']})
        glFinish()
        sel.drainAsyncPicks(mode)
        assert ev.paths == [[]]                     # no id read -> empty path
        assert ev.viewCoordinate == (-4, -4, 1.0)

    def test_unmapped_id_resolves_empty(self, gl_context):
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.submitAsyncPicks(mode, {'k': ev}, {})   # id present but not in map
        glFinish()
        sel.drainAsyncPicks(mode)
        assert ev.paths == [[]]

    def test_unsignalled_fence_defers_batch(self, gl_context, monkeypatch):
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.submitAsyncPicks(mode, {'k': ev}, {ENCODED_ID: ['p']})
        # Force drain to see the fence as not-yet-signalled.
        monkeypatch.setattr(asyncpick, 'glClientWaitSync', lambda *a, **k: 0)
        sel.drainAsyncPicks(mode)
        assert len(sel._async_batches) == 1         # kept for a later frame
        assert ev.paths is None                     # not dispatched yet

    def test_blocking_resolve_drops_batch_when_fence_never_signals(
            self, gl_context, monkeypatch):
        # A blocking resolve whose fence times out must NOT read the PBO or
        # dispatch: the GPU write hasn't landed, so any id would be stale/zero.
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.submitAsyncPicks(mode, {'k': ev}, {ENCODED_ID: ['p']})
        batch = sel._async_batches.pop(0)
        monkeypatch.setattr(asyncpick, 'glClientWaitSync', lambda *a, **k: 0)
        reads = {'n': 0}
        orig = sel._readPBO
        sel._readPBO = lambda *a, **k: (reads.__setitem__('n', reads['n'] + 1)
                                        or orig(*a, **k))
        sel._resolveBatch(mode, batch, block=True)
        assert reads['n'] == 0                      # PBO untouched
        assert ev.paths is None                     # not dispatched
        assert mode.context.processed == []

    def test_overflow_blocks_on_oldest_batch(self, gl_context):
        sel = _bare()
        _attach_buffer(sel, _buffer_with_id())
        sel._ASYNC_MAX_INFLIGHT = 1                  # force the bounded-queue drain
        mode = FakeMode()
        events = [FakeEvent(8, 8) for _ in range(3)]
        for i, ev in enumerate(events):
            sel.submitAsyncPicks(mode, {i: ev}, {ENCODED_ID: ['p']})
        # With max-inflight 1, submitting 3 batches must have force-resolved the
        # older ones (block=True path), delivering their events.
        assert len(sel._async_batches) <= 1
        assert len(mode.context.processed) >= 2
