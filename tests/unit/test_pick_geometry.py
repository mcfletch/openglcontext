"""The arithmetic X3D's pick sensors are answered with (scenegraph.pickgeometry)"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import pickgeometry as pg


def cube(half=1.0, centre=(0.0, 0.0, 0.0)):
    """A closed cube's triangles, (n, 3, 3), wound outward"""
    h = half
    c = np.asarray(centre, dtype=float)
    corners = np.array([(x, y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)]) + c
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    triangles = []
    for a, b, cc, d in faces:
        triangles.append((corners[a], corners[b], corners[cc]))
        triangles.append((corners[a], corners[cc], corners[d]))
    return np.asarray(triangles, dtype=float)


def test_a_segment_through_a_cube_crosses_two_faces():
    hits = pg.segment_triangles(np.array([[0.2, 0.1, 5.0]]), np.array([[0.2, 0.1, -5.0]]), cube())
    assert len(hits.segment) == 2
    assert sorted(np.round(hits.t, 6)) == [0.4, 0.6]
    u, v = hits.u, hits.v
    assert np.all((u >= 0) & (v >= 0) & (u + v <= 1))


def test_a_segment_short_of_the_cube_crosses_nothing():
    hits = pg.segment_triangles(np.array([[0.0, 0.0, 5.0]]), np.array([[0.0, 0.0, 2.0]]), cube())
    assert len(hits.segment) == 0


def test_a_segment_parallel_to_a_face_crosses_nothing():
    triangle = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=float)
    hits = pg.segment_triangles(np.array([[-1.0, 0.2, 0.0]]), np.array([[2.0, 0.2, 0.0]]), triangle)
    assert len(hits.segment) == 0


def test_no_segments_or_no_triangles_cross_nothing():
    assert len(pg.segment_triangles(np.zeros((0, 3)), np.zeros((0, 3)), cube()).t) == 0
    assert len(pg.segment_triangles(np.zeros((1, 3)), np.ones((1, 3)), np.zeros((0, 3, 3))).t) == 0


def test_points_inside_a_closed_mesh_wind_once():
    points = np.array([[0, 0, 0], [0.9, -0.9, 0.5], [1.5, 0, 0], [0, 0, -3]], dtype=float)
    assert list(pg.inside_mesh(points, cube())) == [True, True, False, False]


def test_inside_does_not_depend_on_winding():
    flipped = cube()[:, ::-1]
    assert list(pg.inside_mesh(np.array([[0.0, 0.0, 0.0]]), flipped)) == [True]


def test_segment_box_finds_the_entry_and_its_face():
    entries = pg.segment_box(np.array([[-5.0, 0.5, 0.0], [0.0, 5.0, 0.0], [3.0, 3.0, 3.0]]),
                             np.array([[5.0, 0.5, 0.0], [0.0, 0.0, 0.0], [4.0, 4.0, 4.0]]),
                             np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]))
    assert list(entries.segment) == [0, 1]
    assert np.allclose(entries.t, [0.4, 0.8])
    assert np.allclose(entries.normal, [[-1, 0, 0], [0, 1, 0]])


def test_a_segment_starting_inside_the_box_enters_at_its_start():
    entries = pg.segment_box(np.array([[0.0, 0.0, 0.0]]), np.array([[5.0, 0.0, 0.0]]),
                             -np.ones(3), np.ones(3))
    assert list(entries.segment) == [0]
    assert entries.t[0] == 0.0


def box(centre, half, matrix=None):
    edges = np.diag(np.asarray(half, dtype=float))
    if matrix is not None:
        edges = edges @ np.asarray(matrix, dtype=float)[:3, :3]
    return pg.Box(np.asarray(centre, dtype=float), edges)


def test_boxes_apart_along_an_axis_do_not_overlap():
    assert not pg.boxes_overlap(box((0, 0, 0), (1, 1, 1)), box((3, 0, 0), (1, 1, 1)))
    assert pg.boxes_overlap(box((0, 0, 0), (1, 1, 1)), box((1.5, 0, 0), (1, 1, 1)))


def test_a_turned_box_is_tested_on_its_own_axes():
    c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
    turned = np.array([[c, s, 0, 0], [-s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    assert pg.boxes_overlap(box((0, 0, 0), (1, 1, 1)), box((2.3, 0, 0), (1, 1, 1), turned))
    assert not pg.boxes_overlap(box((0, 0, 0), (1, 1, 1)), box((2.5, 0, 0), (1, 1, 1), turned))


def test_box_from_bounds_and_a_matrix():
    found = pg.Box.from_bounds(np.array([0.0, 0, 0]), np.array([2.0, 2, 2]),
                               np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [5, 0, 0, 1.0]]))
    assert np.allclose(found.centre, (6, 1, 1))
    assert np.allclose(found.edges, np.identity(3))
    assert np.allclose(found.low, (5, 0, 0)) and np.allclose(found.high, (7, 2, 2))


def test_triangles_meet_a_box_where_they_cross_or_sit_in_it():
    triangles = np.array([
        [[-5, 0, -5], [5, 0, -5], [0, 0, 5]],           # slices through
        [[0.1, 0.1, 0.1], [0.2, 0.1, 0.1], [0.1, 0.2, 0.1]],  # inside
        [[3, 3, 3], [4, 3, 3], [3, 4, 3]],               # apart
        [[1.5, 0, 0], [0, 1.5, 0], [0, 0, 1.5]],         # cuts the corner
        [[3.1, 0, 0], [0, 3.1, 0], [0, 0, 3.1]],         # beyond the corner
    ], dtype=float)
    assert list(pg.BoxVolume(np.ones(3)).meets_each(triangles)) == [True, True, False, True, False]


def test_triangles_meet_a_sphere_by_their_nearest_point():
    triangles = np.array([
        [[-5, 0.5, -5], [5, 0.5, -5], [0, 0.5, 5]],     # face within the radius
        [[0.9, 0.9, 0.0], [2, 0.9, 0], [0.9, 2, 0]],    # corner outside, nearest point 1.27 away
        [[-2, 0.0, 0.9], [2, 0.0, 0.9], [0, 5, 0.9]],    # edge 0.9 from the centre
        [[0.1, 0, 0], [0.2, 0, 0], [0.1, 0.1, 0]],       # inside
    ], dtype=float)
    assert list(pg.SphereVolume(1.0).meets_each(triangles)) == [True, False, True, True]


def test_a_sphere_contains_points_within_its_radius():
    assert list(pg.SphereVolume(2.0).contains(np.array([[0, 0, 1.9], [0, 2.1, 0]]))) == [True, False]


def test_a_mesh_volume_meets_a_surface_through_it_or_within_it():
    volume = pg.MeshVolume(cube())
    through = np.array([[[-5, 0, -5], [5, 0, -5], [0, 0, 5]]], dtype=float)
    within = np.array([[[0.1, 0, 0], [0.2, 0, 0], [0.1, 0.1, 0]]], dtype=float)
    apart = np.array([[[3, 0, 0], [4, 0, 0], [3, 1, 0]]], dtype=float)
    assert volume.meets(through)
    assert volume.meets(within)
    assert not volume.meets(apart)


def test_a_mesh_volume_meets_a_surface_that_only_its_edge_crosses():
    # A large square whose interior the small cube pokes through: no vertex of
    # either is inside the other, an edge of the cube crosses the square
    square = np.array([[[-5, 0.5, -5], [5, 0.5, -5], [5, 0.5, 5]],
                       [[-5, 0.5, -5], [5, 0.5, 5], [-5, 0.5, 5]]], dtype=float)
    assert pg.MeshVolume(cube()).meets(square)


def test_a_volume_inside_a_target_meets_it():
    assert pg.target_meets(pg.SphereVolume(1.0), cube(half=10.0))
    assert not pg.target_meets(pg.SphereVolume(1.0), cube(half=10.0, centre=(30, 0, 0)))
    assert not pg.target_meets(pg.SphereVolume(1.0), np.zeros((0, 3, 3)))


@pytest.mark.parametrize('sides', [8, 32])
def test_cylinder_and_cone_solids_are_closed(sides):
    for triangles in (pg.cylinder_solid(1.0, 2.0, sides), pg.cone_solid(1.0, 2.0, sides)):
        assert pg.inside_mesh(np.array([[0.0, -0.5, 0.0]]), triangles)[0]
        assert not pg.inside_mesh(np.array([[0.0, 1.5, 0.0]]), triangles)[0]
        assert not pg.inside_mesh(np.array([[1.2, 0.0, 0.0]]), triangles)[0]


def test_non_finite_points_are_outside():
    points = np.array([[np.nan, 0, 0], [np.inf, 0, 0]])
    assert not pg.inside_mesh(points, cube()).any()
    assert not pg.SphereVolume(1.0).contains(points).any()


def test_primitive_solids_are_centred_and_any_meeting_triangle_meets_them():
    assert np.allclose(pg.BoxVolume(np.ones(3)).centre, 0)
    assert np.allclose(pg.SphereVolume(1.0).centre, 0)
    assert list(pg.BoxVolume(np.ones(3)).contains(np.array([[0.5, 0, 0], [2, 0, 0]]))) == [True, False]
    near = np.array([[[0.1, 0, 0], [0.2, 0, 0], [0.1, 0.1, 0]]], dtype=float)
    assert pg.SphereVolume(1.0).meets(near) and pg.BoxVolume(np.ones(3)).meets(near)


def test_an_empty_mesh_volume_meets_nothing():
    assert not pg.MeshVolume(np.zeros((0, 3, 3))).meets(cube())
    assert not pg.MeshVolume(cube()).meets(np.zeros((0, 3, 3)))
