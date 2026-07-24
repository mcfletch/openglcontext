"""Mirror-aware front-face winding.

A negative-determinant (mirrored) modelview flips triangle winding; the shared
`winding.front_face` follows it so solid VRML97 geometry doesn't cull the wrong
side under mirrored transforms (only pbrmesh handled this before).
"""
import types

import numpy as np
import pytest

from OpenGLContext.scenegraph import winding
from OpenGL.GL import GL_CCW, GL_CW

IDENT = np.identity(4, 'f')
MIRROR_X = np.diag([-1.0, 1.0, 1.0, 1.0]).astype('f')       # one axis flipped
MIRROR_XYZ = np.diag([-1.0, -1.0, -1.0, 1.0]).astype('f')   # three -> det<0


class TestFrontFace:
    def test_no_matrix_uses_base(self):
        assert winding.front_face(True) == GL_CCW
        assert winding.front_face(False) == GL_CW

    def test_identity_keeps_base(self):
        assert winding.front_face(True, IDENT) == GL_CCW
        assert winding.front_face(False, IDENT) == GL_CW

    def test_single_axis_mirror_flips(self):
        assert winding.front_face(True, MIRROR_X) == GL_CW
        assert winding.front_face(False, MIRROR_X) == GL_CCW

    def test_triple_mirror_flips(self):
        # det = -1 -> flipped
        assert winding.front_face(True, MIRROR_XYZ) == GL_CW

    def test_positive_scale_does_not_flip(self):
        s = np.diag([2.0, 3.0, 0.5, 1.0]).astype('f')   # det>0
        assert winding.front_face(True, s) == GL_CCW

    def test_malformed_matrix_falls_back_to_base(self):
        # A matrix the determinant helper can't index must not crash the draw;
        # it degrades to the geometry's own winding.
        class Bad:
            def __getitem__(self, i):
                raise ValueError("no rows here")
        assert winding.front_face(True, Bad()) == GL_CCW
        assert winding.front_face(False, Bad()) == GL_CW


glfw = pytest.importorskip("glfw")
from OpenGL.GL import (   # noqa: E402
    GL_CULL_FACE, GL_FRONT_FACE, glGetIntegerv, glIsEnabled,
)


@pytest.fixture
def gl():
    if not glfw.init():
        pytest.skip("glfw init failed (no GL)")
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    win = glfw.create_window(32, 32, "winding", None, None)
    if not win:
        glfw.terminate()
        pytest.skip("no GL context available")
    glfw.make_context_current(win)
    try:
        yield win
    finally:
        glfw.destroy_window(win)
        glfw.terminate()


class TestApplyWindingCull:
    def test_solid_enables_cull_and_sets_mirror_aware_front_face(self, gl):
        mode = types.SimpleNamespace(matrix=MIRROR_X)
        winding.apply_winding_cull(mode, ccw=True, solid=True)
        assert glIsEnabled(GL_CULL_FACE)
        # CCW geometry under a single-axis mirror draws CW-front.
        assert int(glGetIntegerv(GL_FRONT_FACE)) == GL_CW

    def test_non_solid_disables_cull(self, gl):
        mode = types.SimpleNamespace(matrix=IDENT)
        winding.apply_winding_cull(mode, ccw=True, solid=False)
        assert not glIsEnabled(GL_CULL_FACE)
        assert int(glGetIntegerv(GL_FRONT_FACE)) == GL_CCW

    def test_missing_matrix_uses_base_winding(self, gl):
        mode = types.SimpleNamespace()          # no .matrix attribute
        winding.apply_winding_cull(mode, ccw=False, solid=True)
        assert int(glGetIntegerv(GL_FRONT_FACE)) == GL_CW
