"""X3D's NURBS rules as arithmetic -- knots, closure, tessellation counts -- with no GL.

:mod:`OpenGLContext.scenegraph.nurbseval` reads the fields of the X3D NURBS
nodes (ISO/IEC 19775-1, 27) as plain arrays: the knot vector a node's own
knots and order give, the curve or surface they describe, and its
tessellation into points, normals and triangles.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import nurbseval

#: A flat 4 by 4 net: x follows u, y follows v, u varying fastest.
PLANE = [(float(x), float(y), 0.0) for y in range(4) for x in range(4)]


class TestKnotVector:
    def test_a_valid_knot_vector_is_kept(self):
        knots = nurbseval.knot_vector([0, 0, 0, 1, 2, 2, 2], 3, 4)
        assert list(knots) == [0, 0, 0, 1, 2, 2, 2]

    @pytest.mark.parametrize('knot', [
        [],                                  # none at all
        [0, 0.25, 0.5, 0.75, 1],             # the wrong length
        [0, 0, 0, 2, 1, 2, 2],               # decreasing
        [0, 0, 0, 0, 1, 1, 1],               # four equal: more than the order
    ])
    def test_another_is_replaced_by_a_clamped_uniform_one(self, knot):
        knots = nurbseval.knot_vector(knot, 3, 4)
        assert np.allclose(knots, [0, 0, 0, 0.5, 1, 1, 1])

    def test_a_closed_default_is_periodic_and_extended(self):
        knots = nurbseval.knot_vector([], 3, 5, closed=True)
        # dimension + order uniform knots, then order - 2 more at the same spacing
        assert len(knots) == 5 + 3 + 1
        assert np.allclose(np.diff(knots), np.diff(knots)[0])


class TestSegments:
    def test_a_positive_tessellation_is_the_count(self):
        assert nurbseval.segments(12, 4, 3, 1) == 12

    def test_a_negative_tessellation_is_per_control_point(self):
        assert nurbseval.segments(-3, 5, 3, 2) == 15

    def test_the_default_follows_the_spans_and_points(self):
        assert nurbseval.segments(0, 4, 3, 1) == nurbseval.SEGMENTS_PER_SPAN
        assert nurbseval.segments(0, 20, 3, 18) == 18 * nurbseval.SEGMENTS_PER_SPAN

    def test_a_straight_direction_defaults_to_its_spans(self):
        assert nurbseval.segments(0, 3, 1, 2) == 2

    def test_a_scale_multiplies_the_count_and_never_reaches_zero(self):
        assert nurbseval.segments(10, 4, 3, 1, scale=2.0) == 20
        assert nurbseval.segments(10, 4, 3, 1, scale=0.01) == 1

    def test_the_count_is_capped(self):
        assert nurbseval.segments(10 ** 9, 4, 3, 1) == nurbseval.MAX_SEGMENTS


class TestWeights:
    def test_one_per_point_is_kept(self):
        assert np.allclose(nurbseval.weights([1, 2, 3], 3), [1, 2, 3])

    def test_the_wrong_count_is_no_weights(self):
        assert nurbseval.weights([1, 2], 3) is None
        assert nurbseval.weights([], 3) is None

    def test_a_weight_that_is_not_positive_is_no_weights(self):
        assert nurbseval.weights([1, 0, 1], 3) is None


class TestCurve:
    def test_a_clamped_curve_starts_and_ends_on_its_end_points(self):
        found = nurbseval.curve([(0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0)], [], 4)
        points = found.sample(8)
        assert len(points) == 9
        assert np.allclose(points[0], (0, 0, 0)) and np.allclose(points[-1], (4, 0, 0))

    def test_a_curve_of_fewer_points_than_its_order_is_none(self):
        assert nurbseval.curve([(0, 0, 0), (1, 0, 0)], [], 3) is None

    def test_an_order_below_two_is_none(self):
        assert nurbseval.curve([(0, 0, 0), (1, 0, 0)], [], 1) is None

    def test_a_rational_quadratic_is_a_circle(self):
        """Control points are given multiplied by their weights, as X3D's are"""
        root = math.sqrt(0.5)
        found = nurbseval.curve([(1, 0, 0), (root, root, 0), (0, 1, 0)], [0, 0, 0, 1, 1, 1], 3,
                                weight=[1, root, 1])
        radii = np.linalg.norm(found.sample(16), axis=1)
        assert np.allclose(radii, 1.0, atol=1e-9)

    def test_a_closed_curve_ends_where_it_starts_without_a_kink(self):
        square = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (1, 0, 0)]
        found = nurbseval.curve(square, [], 3, closed=True)
        points = found.sample(40)
        assert np.allclose(points[0], points[-1])
        start = found.tangent_at([0.0])[0]
        end = found.tangent_at([1.0])[0]
        assert np.allclose(start / np.linalg.norm(start), end / np.linalg.norm(end), atol=1e-6)

    def test_a_closed_curve_with_clamped_knots_is_evaluated_as_given(self):
        root = math.sqrt(0.5)
        circle = [(1, 0, 0), (root, -root, 0), (0, -1, 0), (-root, -root, 0), (-1, 0, 0),
                  (-root, root, 0), (0, 1, 0), (root, root, 0), (1, 0, 0)]
        found = nurbseval.curve(circle, [0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4], 3,
                                weight=[1, root] * 4 + [1], closed=True)
        points = found.sample(32)
        assert np.allclose(np.linalg.norm(points, axis=1), 1.0)
        assert np.allclose(points[0], points[-1])

    def test_closed_is_ignored_where_the_ends_differ(self):
        found = nurbseval.curve([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0)], [], 3, closed=True)
        assert not found.closed

    def test_two_dimensional_control_points(self):
        found = nurbseval.curve([(0, 0), (1, 1), (2, 0)], [], 2)
        assert found.sample(2).shape == (3, 2)

    def test_the_tangent_follows_the_curve(self):
        found = nurbseval.curve([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [], 2)
        tangent = found.tangent_at([0.25])[0]
        assert tangent[0] > 0 and np.allclose(tangent[1:], 0)

    def test_a_rational_tangent_is_tangent_to_the_circle(self):
        root = math.sqrt(0.5)
        found = nurbseval.curve([(1, 0, 0), (root, root, 0), (0, 1, 0)], [0, 0, 0, 1, 1, 1], 3,
                                weight=[1, root, 1])
        fractions = np.linspace(0, 1, 7)
        points = found.at(fractions)
        tangents = found.tangent_at(fractions)
        assert np.allclose(np.einsum('ij,ij->i', points, tangents), 0, atol=1e-9)


def _plane(**named):
    fields = dict(points=PLANE, u_dimension=4, v_dimension=4, u_knot=[], v_knot=[],
                  u_order=4, v_order=4)
    fields.update(named)
    return nurbseval.surface(**fields)


class TestSurface:
    def test_a_plane_faces_u_cross_v(self):
        patch = _plane().tessellate(4, 4)
        assert np.allclose(patch.normals, (0, 0, 1))
        a, b, c = (patch.positions[patch.triangles[:, i]] for i in range(3))
        assert (np.cross(b - a, c - a)[:, 2] > 0).all()

    def test_the_lattice_has_one_more_point_than_segments_each_way(self):
        patch = _plane().tessellate(5, 3)
        assert len(patch.positions) == 6 * 4
        assert len(patch.triangles) == 5 * 3 * 2

    def test_fractions_run_u_then_v_over_the_unit_square(self):
        patch = _plane().tessellate(2, 2)
        for point, (s, t) in zip(patch.positions, patch.fractions):
            assert np.allclose(point[:2], (3 * s, 3 * t))

    def test_too_few_points_for_the_dimensions_is_none(self):
        assert _plane(points=PLANE[:10]) is None

    def test_a_dimension_below_the_order_is_none(self):
        assert _plane(u_dimension=2, v_dimension=8) is None

    def test_weights_shape_the_surface(self):
        weight = [1.0] * 16
        weight[5] = 10.0
        plain = _plane(points=[(x, y, 1.0 if (x, y) == (1, 1) else 0.0)
                               for y in range(4) for x in range(4)])
        # the weighted point given multiplied by its weight: (1, 1, 1) at 10
        pulled = _plane(points=[(10.0, 10.0, 10.0) if (x, y) == (1, 1) else (x, y, 0.0)
                                for y in range(4) for x in range(4)], weight=weight)
        assert pulled.tessellate(6, 6).positions[:, 2].max() > \
            plain.tessellate(6, 6).positions[:, 2].max()

    def test_a_surface_closed_in_u_is_seamless(self):
        ring = []
        for height in (0.0, 1.0):
            for angle in np.linspace(0, 2 * math.pi, 7):
                ring.append((math.cos(angle), math.sin(angle), height))
        tube = nurbseval.surface(ring, 7, 2, [], [], 3, 2, u_closed=True)
        assert tube.u_closed
        patch = tube.tessellate(24, 1)
        first = patch.positions.reshape(25, 2, 3)[0]
        last = patch.positions.reshape(25, 2, 3)[-1]
        assert np.allclose(first, last)
        assert np.allclose(patch.normals.reshape(25, 2, 3)[0],
                           patch.normals.reshape(25, 2, 3)[-1])

    def test_evaluating_at_fractions(self):
        positions, normals = _plane().at([(0.5, 0.5), (0.0, 1.0)])
        assert np.allclose(positions, [(1.5, 1.5, 0), (0, 3, 0)])
        assert np.allclose(normals, (0, 0, 1))


class TestTrimming:
    def test_an_outer_loop_and_a_hole(self):
        outer = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], float)
        hole = np.array([(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)], float)
        surface = _plane(u_knot=[0, 0, 0, 0, 1, 1, 1, 1], v_knot=[0, 0, 0, 0, 1, 1, 1, 1])
        patch = surface.tessellate(8, 8, contours=[outer, hole])
        assert _area(patch) == pytest.approx(9 * 0.75, rel=1e-6)

    def test_either_winding_cuts_the_same_hole(self):
        outer = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], float)
        hole = np.array([(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)], float)
        surface = _plane(u_knot=[0, 0, 0, 0, 1, 1, 1, 1], v_knot=[0, 0, 0, 0, 1, 1, 1, 1])
        one = surface.tessellate(8, 8, contours=[outer, hole])
        other = surface.tessellate(8, 8, contours=[outer[::-1], hole])
        assert _area(one) == pytest.approx(_area(other))

    def test_trims_are_in_the_knots_own_range(self):
        surface = _plane(u_knot=[0, 0, 0, 0, 2, 2, 2, 2], v_knot=[0, 0, 0, 0, 2, 2, 2, 2])
        half = np.array([(0, 0), (1, 0), (1, 2), (0, 2)], float)
        assert _area(surface.tessellate(8, 8, contours=[half])) == pytest.approx(4.5, rel=1e-6)

    def test_a_trim_past_the_domain_is_clipped_to_it(self):
        surface = _plane(u_knot=[0, 0, 0, 0, 1, 1, 1, 1], v_knot=[0, 0, 0, 0, 1, 1, 1, 1])
        wide = np.array([(-1, -1), (2, -1), (2, 0.5), (-1, 0.5)], float)
        assert _area(surface.tessellate(8, 8, contours=[wide])) == pytest.approx(4.5, rel=1e-6)

    def test_trimmed_vertices_lie_on_the_surface(self):
        surface = _plane(points=[(x, y, (x - 1.5) ** 2) for y in range(4) for x in range(4)])
        hole = np.array([(0.3, 0.3), (0.6, 0.3), (0.6, 0.6)], float)
        outer = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], float)
        patch = surface.tessellate(6, 6, contours=[outer, hole])
        positions, _ = surface.at(patch.fractions)
        assert np.allclose(positions, patch.positions)

    def test_a_trimmed_surface_is_sampled_as_finely_as_its_lattice_each_way(self):
        """Twenty segments along u and one along v give triangles a twentieth wide"""
        surface = _plane(u_knot=[0, 0, 0, 0, 1, 1, 1, 1], v_knot=[0, 0, 0, 0, 1, 1, 1, 1])
        notch = np.array([(0, 0), (1, 0), (0.75, 0.5), (1, 1), (0, 1)], float)
        patch = surface.tessellate(20, 1, contours=[notch])
        corners = patch.fractions[patch.triangles]
        widths = corners[:, :, 0].max(axis=1) - corners[:, :, 0].min(axis=1)
        assert widths.max() <= 1.5 / 20

    def test_trimming_everything_away_is_empty(self):
        surface = _plane()
        outside = np.array([(5, 5), (6, 5), (6, 6)], float)
        assert not len(surface.tessellate(4, 4, contours=[outside]).triangles)


class TestTextureNets:
    def test_a_coordinate_net_follows_the_surface_basis(self):
        surface = _plane()
        corners = [(s * 2.0, t * 2.0) for t in np.linspace(0, 1, 4) for s in np.linspace(0, 1, 4)]
        net = surface.coordinate_net(corners)
        found = net.at([(0, 0), (1, 1), (0.5, 0.5)])
        assert np.allclose(found, [(0, 0), (2, 2), (1, 1)])

    def test_a_short_coordinate_net_is_none(self):
        assert _plane().coordinate_net([(0, 0)] * 3) is None

    def test_a_nurbs_texture_coordinate_has_its_own_net(self):
        net = nurbseval.texture_net([(0, 0), (4, 0), (0, 4), (4, 4)], 2, 2, [], [], 2, 2)
        assert np.allclose(net.at([(0.25, 0.5)]), [(1, 2)])


class TestSweeps:
    def test_a_swept_surface_follows_its_trajectory(self):
        section = nurbseval.curve([(-1, 0), (1, 0), (1, 1), (-1, 1), (-1, 0)], [], 2)
        trajectory = nurbseval.curve([(0, 0, 0), (0, 2, 0), (0, 4, 0)], [], 2)
        mesh = nurbseval.swept(section, trajectory, ccw=True)
        positions = mesh.attributes['POSITION']
        assert positions[:, 1].min() == pytest.approx(0) and positions[:, 1].max() == pytest.approx(4)
        assert len(mesh.indices)

    def test_a_swung_surface_lies_along_its_trajectory_in_xz(self):
        profile = nurbseval.curve([(0.5, 0), (0.5, 1)], [], 2)
        # counter-clockwise looking down -y, which puts the profile's y up
        trajectory = nurbseval.curve([(-2, 0), (0, 2), (2, 0)], [], 2)
        mesh = nurbseval.swung(profile, trajectory, ccw=True)
        positions = mesh.attributes['POSITION']
        assert positions[:, 1].min() == pytest.approx(0) and positions[:, 1].max() == pytest.approx(1)
        assert np.abs(positions[:, 2]).max() > 1.5


def _area(patch):
    a, b, c = (patch.positions[patch.triangles[:, i]] for i in range(3))
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
