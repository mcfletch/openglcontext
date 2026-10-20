"""Which boxes lie wholly behind a clipping plane."""
import numpy as np

from OpenGLContext.frustum import boxes_outside


def _boxes(count=500, seed=11):
    rng = np.random.default_rng(seed)
    return rng.uniform(-50.0, 50.0, (count, 3)), rng.uniform(0.1, 6.0, (count, 3))


def _planes(seed=5):
    rng = np.random.default_rng(seed)
    normals = rng.normal(size=(6, 3))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    return np.concatenate([normals, rng.uniform(-30.0, 30.0, (6, 1))], axis=1)


class TestBoxesInTheSpaceOfThePlanes:
    def test_no_matrices_is_the_same_as_identity_matrices(self) -> None:
        centres, halves = _boxes()
        planes = _planes()
        placed = np.broadcast_to(np.eye(4), (len(centres), 4, 4))
        assert np.array_equal(boxes_outside(centres, halves, None, planes),
                              boxes_outside(centres, halves, placed, planes))

    def test_some_boxes_are_outside_and_some_are_not(self) -> None:
        centres, halves = _boxes()
        outside = boxes_outside(centres, halves, None, _planes()[:2])
        assert outside.any()
        assert not outside.all()

    def test_a_box_straddling_a_plane_is_not_outside(self) -> None:
        plane = np.array([[1.0, 0.0, 0.0, 0.0]])
        assert not boxes_outside([[-1.0, 0.0, 0.0]], [[2.0, 1.0, 1.0]], None, plane)[0]
        assert boxes_outside([[-3.0, 0.0, 0.0]], [[2.0, 1.0, 1.0]], None, plane)[0]

    def test_one_box_may_stand_for_every_row(self) -> None:
        assert boxes_outside(np.zeros(3), np.ones(3), None, np.array([[0.0, 0.0, 1.0, -5.0]])).shape == (1,)
