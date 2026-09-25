"""Depth ordering of the transparent-triangle sort.

Alpha blending is order-dependent: a triangle must be composited over what is
behind it, so the draw order for transparent geometry is back to front.
``polygonsort.distances`` reports window z, which grows with distance from the
eye, so the farthest triangle has the largest value and must come first.
"""

import numpy as np

from OpenGLContext.scenegraph import polygonsort

#: A standard perspective projection, row-vector convention: near 1, far 100.
NEAR, FAR = 1.0, 100.0
PROJECTION = np.array(
    [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, -(FAR + NEAR) / (FAR - NEAR), -1],
        [0, 0, -2 * FAR * NEAR / (FAR - NEAR), 0],
    ],
    'f',
)
MODELVIEW = np.identity(4, 'f')
VIEWPORT = np.array([0, 0, 100, 100], 'f')


def _distances(points):
    return polygonsort.distances(
        np.asarray(points, 'f'),
        modelView=MODELVIEW,
        projection=PROJECTION,
        viewport=VIEWPORT,
    )


def test_distance_grows_with_distance_from_the_eye():
    near, middle, far = _distances([[0, 0, -2], [0, 0, -5], [0, 0, -50]])
    assert near < middle < far


def test_indices_draw_the_farthest_triangle_first():
    """Triangle 1 is the farthest away, so its vertices lead the index array."""
    order = polygonsort.indices(_distances([[0, 0, -2], [0, 0, -50], [0, 0, -5]]))
    assert list(order) == [3, 4, 5, 6, 7, 8, 0, 1, 2]


def test_indices_expands_each_triangle_to_its_three_vertices():
    order = polygonsort.indices(_distances([[0, 0, -2], [0, 0, -5]]))
    assert len(order) == 6
    assert list(order[0:3]) == [3, 4, 5]
    assert list(order[3:6]) == [0, 1, 2]


def test_sort_index_puts_the_farthest_polygon_first():
    """An indexed set keeps its own vertex indices, reordered polygon by polygon."""
    index = np.array([7, 8, 9, 1, 2, 3], 'I')
    ordered = polygonsort.sortIndex(
        index, _distances([[0, 0, -2], [0, 0, -50]]), 3)
    assert [list(row) for row in ordered] == [[1, 2, 3], [7, 8, 9]]


def test_sort_index_handles_quads():
    index = np.array([0, 1, 2, 3, 4, 5, 6, 7], 'I')
    ordered = polygonsort.sortIndex(
        index, _distances([[0, 0, -50], [0, 0, -2]]), 4)
    assert [list(row) for row in ordered] == [[0, 1, 2, 3], [4, 5, 6, 7]]


def test_a_point_in_the_eye_plane_has_a_finite_distance():
    """A triangle reaching the eye's plane has w = 0 at that corner."""
    found = _distances([[0, 0, 0], [0, 0, -5], [1, 0, 0]])
    assert np.all(np.isfinite(found)), found


def test_project_gives_window_coordinates_for_every_point():
    found = polygonsort.project(np.asarray([[0, 0, -2], [1, 1, -1], [-2, 0, -4]], 'f'),
                                modelView=MODELVIEW, projection=PROJECTION,
                                viewport=VIEWPORT)
    assert found.shape == (3, 3)
    assert np.allclose(found[0, :2], (50, 50))
    assert np.allclose(found[1, :2], (100, 100))
    assert np.allclose(found[2, :2], (25, 50))
    assert found[0, 2] < found[2, 2]
