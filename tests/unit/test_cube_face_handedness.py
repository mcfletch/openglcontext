"""The point-light cube-face view matrices were unverified against
GL's cube-map convention. These pin the six faces: each face's view must look
straight down its world axis (the face forward direction maps to view -Z, per the
right-handed look_at that feeds the left-handed cube sampler), with the documented
up vector landing on +Y. A silent sign flip in CUBE_FACES then fails a test rather
than producing phantom / rotated point shadows.
"""
import numpy as np
import pytest

from OpenGLContext.passes import shadowmath


EXPECTED_FACES = [
    ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),   # +X
    ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),  # -X
    ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),    # +Y
    ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),  # -Y
    ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),   # +Z
    ((0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),  # -Z
]


class TestCubeFaceConvention:
    def test_face_table_matches_gl_convention(self):
        assert shadowmath.CUBE_FACES == EXPECTED_FACES

    @pytest.mark.parametrize("face", range(6))
    def test_forward_maps_to_negative_z(self, face):
        view = np.asarray(shadowmath.cube_face_view((0.0, 0.0, 0.0), face), dtype='d')
        forward = np.array(list(EXPECTED_FACES[face][0]) + [0.0])
        eye = forward @ view      # row-vector convention
        assert eye[2] < 0.0                      # looks down its axis
        assert abs(eye[0]) < 1e-5 and abs(eye[1]) < 1e-5
        assert eye[2] == pytest.approx(-1.0, abs=1e-5)

    @pytest.mark.parametrize("face", range(6))
    def test_up_maps_to_positive_y(self, face):
        view = np.asarray(shadowmath.cube_face_view((0.0, 0.0, 0.0), face), dtype='d')
        up = np.array(list(EXPECTED_FACES[face][1]) + [0.0])
        eye = up @ view
        assert eye[1] == pytest.approx(1.0, abs=1e-5)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
