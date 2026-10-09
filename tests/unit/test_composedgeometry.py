"""X3D composed geometry as glTF-shaped arrays, with no GL.

`composedgeometry` turns the fields of X3D's triangle and line sets into
triangles (or segments) of coordinate indices, and those into the attribute
arrays and indices a `PBRMesh` is built from.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import composedgeometry as cg

SQUARE = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f')


class TestTriangles:
    def test_a_triangle_set_takes_its_points_three_at_a_time(self):
        assert cg.triangle_set(7).tolist() == [[0, 1, 2], [3, 4, 5]]

    def test_an_indexed_triangle_set_takes_its_index_three_at_a_time(self):
        assert cg.indexed_triangles([0, 1, 2, 0, 2, 3, 9]).tolist() == [[0, 1, 2], [0, 2, 3]]

    def test_a_fan_turns_about_its_first_point(self):
        assert cg.fans([5]).tolist() == [[0, 1, 2], [0, 2, 3], [0, 3, 4]]

    def test_fans_follow_one_another(self):
        assert cg.fans([3, 4]).tolist() == [[0, 1, 2], [3, 4, 5], [3, 5, 6]]

    def test_a_strip_alternates_its_winding(self):
        assert cg.strips([5]).tolist() == [[0, 1, 2], [2, 1, 3], [2, 3, 4]]

    def test_a_count_below_three_makes_nothing(self):
        assert cg.fans([2, 3]).tolist() == [[2, 3, 4]]
        assert cg.strips([1]).shape == (0, 3)

    def test_indexed_fans_and_strips_split_at_minus_one(self):
        assert cg.indexed_fans([0, 1, 2, 3, -1, 4, 5, 6]).tolist() == [
            [0, 1, 2], [0, 2, 3], [4, 5, 6]]
        assert cg.indexed_strips([0, 1, 2, 3, -1]).tolist() == [[0, 1, 2], [2, 1, 3]]

    def test_line_segments_follow_vertex_counts(self):
        assert cg.line_segments([3, 2]).tolist() == [[0, 1], [1, 2], [3, 4]]


class TestArrays:
    def test_per_vertex_attributes_keep_the_points_shared(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]))
        assert len(made.attributes['POSITION']) == 4
        assert made.indices.tolist() == [0, 1, 2, 0, 2, 3]

    def test_generated_normals_face_the_counter_clockwise_side(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]))
        assert np.allclose(made.attributes['NORMAL'], (0, 0, 1))

    def test_clockwise_faces_are_turned_round(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]), ccw=False)
        assert made.indices.tolist() == [0, 2, 1]
        assert np.allclose(made.attributes['NORMAL'][made.indices], (0, 0, -1))

    def test_per_face_colours_split_the_corners(self):
        colours = np.array([(1, 0, 0), (0, 1, 0)], 'f')
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]),
                                  colors=colours, color_per_vertex=False)
        assert made.indices is None
        assert made.attributes['COLOR_0'].tolist() == [[1, 0, 0]] * 3 + [[0, 1, 0]] * 3
        assert len(made.attributes['POSITION']) == 6

    def test_shared_points_are_their_own_sources(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]))
        assert made.sources.tolist() == [0, 1, 2, 3]

    def test_split_corners_name_the_point_each_was_read_from(self):
        colours = np.array([(1, 0, 0), (0, 1, 0)], 'f')
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]),
                                  colors=colours, color_per_vertex=False)
        assert made.sources.tolist() == [0, 1, 2, 0, 2, 3]

    def test_per_face_normals_are_flat(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]),
                                  normal_per_vertex=False)
        assert np.allclose(made.attributes['NORMAL'], (0, 0, 1))
        assert len(made.attributes['NORMAL']) == 3

    def test_given_normals_are_used(self):
        given = np.tile([0, 1, 0], (4, 1)).astype('f')
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]), normals=given)
        assert np.allclose(made.attributes['NORMAL'], (0, 1, 0))

    def test_rgba_colours_keep_their_alpha(self):
        colours = np.array([(1, 0, 0, 0.5)] * 4, 'f')
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]), colors=colours)
        assert made.attributes['COLOR_0'].shape == (4, 4)

    def test_two_coordinate_sets_are_texcoord_0_and_1(self):
        first = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f')
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]),
                                  texcoords=[first, first * 2])
        assert np.allclose(made.attributes['TEXCOORD_1'], first * 2)

    def test_given_tangents_follow_their_points(self):
        given = np.tile([1, 0, 0, -1], (4, 1)).astype('f')
        shared = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]), tangents=given)
        split = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]), tangents=given,
                                   normal_per_vertex=False)
        assert shared.attributes['TANGENT'].shape == (4, 4)
        assert split.attributes['TANGENT'].shape == (3, 4)

    def test_an_index_past_the_points_drops_its_triangle(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 9]))
        assert made.indices.tolist() == [0, 1, 2]
        assert made.dropped == 1

    def test_an_attribute_too_short_for_the_points_is_left_out(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2]),
                                  colors=np.array([(1, 0, 0)], 'f'))
        assert 'COLOR_0' not in made.attributes
        assert made.short == ['color']

    @pytest.mark.parametrize('bad', [np.nan, np.inf])
    def test_non_finite_points_are_kept_as_given(self, bad):
        points = SQUARE.copy()
        points[3] = bad
        made = cg.composed_arrays(points, cg.indexed_triangles([0, 1, 2]))
        assert np.isfinite(made.attributes['NORMAL']).all()

    def test_no_triangles_makes_an_empty_mesh(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([]))
        assert len(made.indices) == 0


#: Two squares meeting at a right-angled fold along x=1.
FOLD = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                 (1, 0, -1), (1, 1, -1)], 'f')
FOLD_TRIANGLES = cg.indexed_triangles([0, 1, 2, 0, 2, 3, 1, 4, 5, 1, 5, 2])


class TestCreaseAngle:
    def test_a_fold_sharper_than_the_crease_angle_stays_sharp(self):
        made = cg.composed_arrays(FOLD, FOLD_TRIANGLES, crease_angle=0.5)
        normals = made.attributes['NORMAL']
        assert np.allclose(normals[:6], (0, 0, 1), atol=1e-6)
        assert np.allclose(normals[6:], (1, 0, 0), atol=1e-6)

    def test_a_fold_within_the_crease_angle_is_smoothed(self):
        made = cg.composed_arrays(FOLD, FOLD_TRIANGLES, crease_angle=2.0)
        positions, normals = made.attributes['POSITION'], made.attributes['NORMAL']
        on_the_fold = np.isclose(positions[:, 0], 1) & np.isclose(positions[:, 2], 0)
        between = normals[on_the_fold]
        assert (between[:, 0] > 0.3).all() and (between[:, 2] > 0.3).all()
        assert np.allclose(np.linalg.norm(between, axis=1), 1.0)

    def test_flat_faces_need_no_crease(self):
        made = cg.composed_arrays(SQUARE, cg.indexed_triangles([0, 1, 2, 0, 2, 3]),
                                  crease_angle=0.0)
        assert np.allclose(made.attributes['NORMAL'], (0, 0, 1))


class TestElevationGrid:
    def test_its_triangles_face_up(self):
        triangles = cg.grid_triangles(3, 2)
        points = cg.grid_points([0, 0, 0, 0, 0, 0], 3, 2, 1.0, 1.0)
        made = cg.composed_arrays(points, triangles)
        assert len(triangles) == 4
        assert np.allclose(made.attributes['NORMAL'], (0, 1, 0))

    def test_its_points_are_spaced_and_raised(self):
        points = cg.grid_points([0, 1, 2, 3], 2, 2, 0.5, 2.0)
        assert points.tolist() == [[0, 0, 0], [0.5, 1, 0], [0, 2, 2], [0.5, 3, 2]]

    def test_its_default_texture_coordinates_span_the_grid(self):
        assert cg.grid_texcoords(3, 2).tolist() == [[0, 0], [0.5, 0], [1, 0],
                                                    [0, 1], [0.5, 1], [1, 1]]

    def test_a_grid_smaller_than_two_by_two_has_no_triangles(self):
        assert cg.grid_triangles(1, 5).shape == (0, 3)

    def test_per_quad_values_cover_both_its_triangles(self):
        assert cg.per_quad([10, 20]).tolist() == [10, 10, 20, 20]
