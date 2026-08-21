"""GL-driven pick paths of :class:`SelectionMixin` that the pure-logic suite can't
reach: the synchronous MRT buffer lookup (``processPickEventsFromBuffer``) against
a real rendered id buffer in a hidden GLFW window.

The full per-pick legacy render loop (``shaderSelectRenderOptimized``) is exercised
end-to-end by test_passes_render_gl's legacy-pick scene; here we cover the fast
zero-render buffer readback + dispatch in isolation with a bare mixin.
"""
import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGL.GL import (  # noqa: E402
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT, glClear, glClearColor, glDrawBuffers, glViewport,
)

from OpenGLContext.passes.selection import SelectionMixin  # noqa: E402
from OpenGLContext.passes.selectionbuffers import SelectionBufferFBO  # noqa: E402


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    win = glfw.create_window(64, 64, "sel-render", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


ENCODED_ID = 7 | (8 << 8) | (9 << 16)   # rgba bytes (7, 8, 9, 0)


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


def _buffer_with_id(size=16):
    sb = SelectionBufferFBO()
    assert sb.ensure_size(size, size)
    sb.bind()
    glViewport(0, 0, size, size)
    glClearColor(0, 0, 0, 0)
    glClear(GL_DEPTH_BUFFER_BIT)
    glDrawBuffers(1, [GL_COLOR_ATTACHMENT1])
    glClearColor(7 / 255.0, 8 / 255.0, 9 / 255.0, 0.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])
    sb.unbind()
    return sb


def _bare(buffer):
    sel = SelectionMixin.__new__(SelectionMixin)
    sel.matrix = np.identity(4, 'f')
    # The camera model-view the picks unproject against. The real pass
    # sets both in setViewPlatform; sel.matrix is then rewritten per node
    # by the traversal, which is why the dispatch reads this one.
    sel.modelView = np.identity(4, 'f')
    sel.projection = np.identity(4, 'f')
    sel.viewport = (0, 0, 16, 16)
    sel._selection_buffer = buffer
    sel._getSelectionBuffer = lambda: buffer
    return sel


class TestProcessPickEventsFromBuffer:
    def test_mapped_id_dispatches_path_and_depth(self, gl_context):
        sb = _buffer_with_id()
        sel = _bare(sb)
        path = ['transform', 'shape']
        sb.set_id_map({ENCODED_ID: path})
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.processPickEventsFromBuffer(mode, {'k': ev})
        # The pixel at (8,8) holds ENCODED_ID, mapped to `path`; the event is
        # populated with that path + a depth and forwarded to the context.
        assert ev.paths == [path]
        assert ev.viewCoordinate[0] == 8 and ev.viewCoordinate[1] == 8
        assert ev.modelViewMatrix is sel.modelView
        assert mode.context.processed == [ev]

    def test_unmapped_id_dispatches_empty_path(self, gl_context):
        sb = _buffer_with_id()
        sel = _bare(sb)
        sb.set_id_map({})               # id present in buffer but not in the map
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.processPickEventsFromBuffer(mode, {'k': ev})
        assert ev.paths == [[]]
        assert mode.context.processed == [ev]

    def test_uninitialized_buffer_is_a_noop(self, gl_context):
        sb = SelectionBufferFBO()       # never ensure_size'd -> not initialized
        sel = _bare(sb)
        mode = FakeMode()
        ev = FakeEvent(8, 8)
        sel.processPickEventsFromBuffer(mode, {'k': ev})
        # falls back (does nothing): event stays unresolved, nothing dispatched.
        assert ev.paths is None
        assert mode.context.processed == []

    def test_empty_events_returns_immediately(self, gl_context):
        sel = _bare(_buffer_with_id())
        sel.processPickEventsFromBuffer(FakeMode(), {})   # no error, no work


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
