"""Coverage tests for the glTF transform/orientation math helpers.

Pure numpy: point bounds, the degenerate-quaternion guard, and the three
non-trace quaternion-from-matrix branches of ``look_orientation`` (large rotations
where the matrix trace is negative). Each look case is checked by the strongest
possible assertion -- the returned axis-angle really rotates the camera's local
-Z onto the requested forward.
"""
import math

import numpy as np
import pytest

from OpenGLContext.loaders.gltf import transforms as gt


def _apply_axis_angle(orientation, v):
    axis = np.asarray(orientation[:3], 'd')
    axis = axis / (np.linalg.norm(axis) or 1.0)
    angle = orientation[3]
    v = np.asarray(v, 'd')
    return (v * math.cos(angle) + np.cross(axis, v) * math.sin(angle)
            + axis * np.dot(axis, v) * (1 - math.cos(angle)))


class TestBoundsFromPoints:
    def test_min_and_max_per_axis(self):
        pts = np.array([[1, -2, 3], [-4, 5, 0], [0, 0, 6]], dtype='f')
        lo, hi = gt._bounds_from_points(pts)
        assert lo.tolist() == [-4, -2, 0]
        assert hi.tolist() == [1, 5, 6]


class TestQuatToXyzrDegenerate:
    def test_zero_quaternion_returns_identity_axis(self):
        # A norm-zero quaternion can't yield an axis; the guard returns +Y/0deg.
        assert gt._quat_to_xyzr([0.0, 0.0, 0.0, 0.0]) == (0.0, 1.0, 0.0, 0.0)


class TestLookOrientationTraceBranches:
    def _check(self, forward, up):
        o = gt.look_orientation(forward, up)
        assert all(np.isfinite(o))
        f = np.asarray(forward, 'd')
        f = f / np.linalg.norm(f)
        assert np.allclose(_apply_axis_angle(o, (0, 0, -1)), f, atol=1e-6)
        return o

    def test_x_axis_dominant_branch(self):
        # forward/up chosen so the camera x-axis is the largest diagonal term.
        self._check((-1.0, -1.0, 1.0 / 3.0), (1, 0, 0))

    def test_z_axis_dominant_branch(self):
        # the fall-through else branch (z-axis diagonal term dominant, trace < 0).
        self._check((-1.0, -1.0, -2.0 / 3.0), (1, 0, 0))

    def test_y_axis_dominant_branch(self):
        # forward straight along +Z with default up: a 180deg turn, y-term dominant.
        self._check((0.0, 0.0, 1.0), (0, 1, 0))


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
