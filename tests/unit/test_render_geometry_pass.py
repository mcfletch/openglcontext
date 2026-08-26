"""``FlatPass.renderGeometry`` draws a scene from a matrix a caller supplies.

The shadow tutorials render the scene a second and third time from each light's
point of view to build its depth map, so they need a way to say "draw everything
visible from *this* matrix" without the rest of a frame around it.  That is what
this is, and it is a published part of the pass -- *Depth-map Shadows* calls it
by name.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import pytest  # noqa: E402

pytest.importorskip("glfw")

from OpenGLContext.passes._flat import FlatPass  # noqa: E402


class _Recording(FlatPass):
    """Records what the two geometry passes were handed, and draws nothing."""

    def __init__(self):
        self.calls = []
        self.rendered = object()

    def renderSet(self, matrix):
        self.calls.append(('renderSet', matrix))
        return self.rendered

    def renderOpaque(self, toRender):
        self.calls.append(('renderOpaque', toRender))

    def renderTransparent(self, toRender):
        self.calls.append(('renderTransparent', toRender))


class TestRenderGeometry:
    def test_it_gathers_from_the_matrix_it_was_given(self):
        pass_ = _Recording()
        pass_.renderGeometry('a-matrix')
        assert pass_.calls[0] == ('renderSet', 'a-matrix')

    def test_both_geometry_passes_draw_what_was_gathered(self):
        pass_ = _Recording()
        pass_.renderGeometry('a-matrix')
        assert [name for name, _ in pass_.calls[1:]] == [
            'renderOpaque', 'renderTransparent']
        assert all(arg is pass_.rendered for _, arg in pass_.calls[1:])
