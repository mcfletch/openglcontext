"""Reading a rotation back out of a matrix.

The inverse of :meth:`Quaternion.matrix`, which is what a consumer needs when
the rotation it has to express arrives as a matrix -- a node's world transform,
a basis built from two directions -- and the thing that has to carry it is a
VRML ``rotation`` field.
"""
import numpy as np
import pytest

from OpenGLContext.quaternion import Quaternion, fromMatrix, fromXYZR

#: Rotations that between them exercise every branch of the reconstruction:
#: the identity, small ones, each axis at 180 degrees, and an oblique one.
ROTATIONS = [
    (0.0, 1.0, 0.0, 0.0),
    (1.0, 0.0, 0.0, 0.7),
    (0.0, 1.0, 0.0, -1.2),
    (0.0, 0.0, 1.0, 2.9),
    (1.0, 0.0, 0.0, np.pi),
    (0.0, 1.0, 0.0, np.pi),
    (0.0, 0.0, 1.0, np.pi),
    (0.577, 0.577, 0.577, 2.1),
    (0.267, -0.535, 0.802, 1.7),
]


class TestReadingARotationOutOfAMatrix:
    @pytest.mark.parametrize('rotation', ROTATIONS)
    def test_the_matrix_it_came_from_comes_back(self, rotation):
        """The property that matters: same rotation, whatever the sign of q."""
        want = fromXYZR(*rotation).matrix(dtype='d')
        assert np.allclose(fromMatrix(want).matrix(dtype='d'), want, atol=1e-9)

    @pytest.mark.parametrize('rotation', ROTATIONS)
    def test_a_point_lands_where_it_did(self, rotation):
        point = np.array([0.3, -0.7, 0.2, 1.0])
        want = fromXYZR(*rotation).matrix(dtype='d')
        assert np.allclose(point @ fromMatrix(want).matrix(dtype='d'),
                           point @ want, atol=1e-9)

    def test_it_answers_a_quaternion(self):
        assert isinstance(fromMatrix(np.eye(4)), Quaternion)

    def test_a_three_by_three_is_enough(self):
        want = fromXYZR(0.0, 1.0, 0.0, 0.6).matrix(dtype='d')
        assert np.allclose(fromMatrix(want[:3, :3]).matrix(dtype='d'), want)

    def test_the_identity_is_no_rotation(self):
        assert fromMatrix(np.eye(3)).XYZR()[3] == pytest.approx(0.0)
