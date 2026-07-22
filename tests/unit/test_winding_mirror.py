"""Mirror-aware front-face winding.

A negative-determinant (mirrored) modelview flips triangle winding; the shared
`winding.front_face` follows it so solid VRML97 geometry doesn't cull the wrong
side under mirrored transforms (only pbrmesh handled this before).
"""
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
