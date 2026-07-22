"""Deferred transparent-shape rendering.

`Shape.Render` calls `mode.addTransparent(self)` and returns without drawing when
a shape statically classed opaque turns out transparent at render time. That
method was a silent no-op, so the shape simply vanished for the frame. It now
records the shape (with its modelview matrix and path) and the transparent pass
replays it via `RenderTransparent`.

The drain issues GL state calls, which are monkeypatched to no-ops here so the
bookkeeping (record → replay → clear) can be checked without a GL context.
"""
import pytest

from OpenGLContext.passes import _flat
from OpenGLContext.passes._flat import FlatPass

_GL_NOOPS = ('glEnable', 'glDisable', 'glBlendFunc', 'glDepthMask',
             'glDepthFunc', 'glLoadMatrixf')


def _bare_pass():
    fp = FlatPass.__new__(FlatPass)
    fp._deferredTransparent = []
    return fp


class TestAddTransparent:
    def test_records_shape_with_matrix_and_path(self):
        fp = _bare_pass()
        fp.matrix = 'MV'
        fp.renderPath = 'PATH'
        shape = object()
        fp.addTransparent(shape)
        assert fp._deferredTransparent == [('MV', 'PATH', shape)]

    def test_lazy_inits_when_unset(self):
        fp = FlatPass.__new__(FlatPass)   # no _deferredTransparent yet
        fp.matrix = None
        fp.renderPath = None
        fp.addTransparent(object())
        assert len(fp._deferredTransparent) == 1


class TestDrain:
    def test_replays_each_deferred_shape_then_clears(self, monkeypatch):
        for name in _GL_NOOPS:
            monkeypatch.setattr(_flat, name, lambda *a, **k: None, raising=False)

        calls = []

        class Shape:
            def __init__(self, tag):
                self.tag = tag

            def RenderTransparent(self, mode):
                calls.append(self.tag)

        fp = _bare_pass()
        fp._deferredTransparent = [('M1', 'P1', Shape('a')), ('M2', 'P2', Shape('b'))]
        fp._renderDeferredTransparent()

        assert calls == ['a', 'b']
        assert fp._deferredTransparent == [], "deferred list must be cleared after draining"

    def test_empty_drain_is_noop(self, monkeypatch):
        for name in _GL_NOOPS:
            monkeypatch.setattr(_flat, name, lambda *a, **k: None, raising=False)
        fp = _bare_pass()
        fp._renderDeferredTransparent()   # must not raise
        assert fp._deferredTransparent == []

    def test_one_failing_shape_does_not_abort_the_rest(self, monkeypatch):
        for name in _GL_NOOPS:
            monkeypatch.setattr(_flat, name, lambda *a, **k: None, raising=False)

        drawn = []

        class Boom:
            def RenderTransparent(self, mode):
                raise RuntimeError("bad shape")

        class Ok:
            def RenderTransparent(self, mode):
                drawn.append(True)

        fp = _bare_pass()
        fp._deferredTransparent = [('M', 'P', Boom()), ('M', 'P', Ok())]
        fp._renderDeferredTransparent()
        assert drawn == [True]
        assert fp._deferredTransparent == []
