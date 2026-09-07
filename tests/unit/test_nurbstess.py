"""Evaluating a NURBS surface node into triangles -- pure CPU, no GL.

:func:`~OpenGLContext.scenegraph.nurbstess.tessellate_surface` reads a surface
node's control net, knots, weights, colours and trimming contours and evaluates
them into positions, normals, parametric texture coordinates and triangle
indices. Nothing in it touches GL, so all of it is testable here; only the
upload in :func:`~OpenGLContext.scenegraph.nurbstess.build_surface_vbo` needs a
context, and that is covered by the NURBS GL tests.

The expected values are the ones the GLU NURBS tessellator produced for the same
nodes -- normal sense, triangle winding, texture-coordinate orientation and
sample counts -- so a scene keeps the surfaces it was authored with.
"""
import numpy as np
import pytest
from opengl_extrusions.nurbs import NurbsError

from OpenGLContext.scenegraph import nurbs
from OpenGLContext.scenegraph.nurbssampling import (
    NurbsDomainDistanceSample, NurbsToleranceSample,
)
from OpenGLContext.scenegraph.nurbstess import (
    DEFAULT_STEP, MAX_INTERVALS, SurfaceTessellation, interleave, intervals_for,
    surface_intervals, tessellate_surface,
)
from OpenGLContext.scenegraph.nurbstrim import Contour2D, NurbsCurve2D, Polyline2D

_KNOT = [0, 0, 0, 0, 1, 1, 1, 1]

#: A plane whose x follows u and whose y follows v, so a swapped parametric
#: direction or a flipped cross product shows up as a sign.
_PLANE = [[float(x), float(y), 0.0] for y in range(4) for x in range(4)]

_CCW = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
_CW = list(reversed(_CCW))
_INNER_CW = list(reversed([[0.3, 0.3], [0.6, 0.3], [0.6, 0.6], [0.3, 0.6]]))


def _surface(**overrides):
    fields = dict(controlPoint=_PLANE, uDimension=4, vDimension=4,
                  uKnot=_KNOT, vKnot=_KNOT)
    fields.update(overrides)
    return nurbs.NurbsSurface(**fields)


def _rings(*loops):
    return [Contour2D(children=[Polyline2D(point=loop)]) for loop in loops]


def _area(tessellation):
    """Area of the triangles projected into xy -- the plane's own extent."""
    p = tessellation.positions[:, :2]
    a, b, c = (p[tessellation.indices[:, i]] for i in range(3))
    e1, e2 = b - a, c - a
    return float(0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum())


class TestSampleCounts:
    """A sampling rate is per unit of knot range, so triangles keep their size."""

    def test_a_rate_over_a_unit_domain_is_the_interval_count(self):
        assert intervals_for(30.0, 1.0) == 30

    def test_a_wider_domain_is_sampled_proportionally(self):
        assert intervals_for(4.0, 4.0) == 16

    def test_it_never_returns_less_than_one(self):
        assert intervals_for(0.1, 0.1) == 1

    def test_a_nonsense_rate_still_gives_a_surface(self):
        assert intervals_for(float('nan'), 1.0) == 1
        assert intervals_for(-5.0, 1.0) == 1

    def test_it_is_capped(self):
        assert intervals_for(1e9, 1.0) == MAX_INTERVALS

    def test_explicit_steps_win_over_the_sampling_node(self):
        node = NurbsDomainDistanceSample(uStep=100, vStep=100)
        assert surface_intervals(_surface(), sampling=node, u_step=8, v_step=8) == (8, 8)

    def test_a_domain_distance_node_states_its_own_rate(self):
        node = NurbsDomainDistanceSample(uStep=12, vStep=20)
        assert surface_intervals(_surface(), sampling=node) == (20, 12)  # v first

    def test_a_tolerance_node_maps_to_a_rate(self):
        node = NurbsToleranceSample(method='screen', parametric=1, tolerance=5)
        assert surface_intervals(_surface(), sampling=node) == (30, 30)

    def test_a_tighter_tolerance_asks_for_more(self):
        loose = NurbsToleranceSample(tolerance=50)
        tight = NurbsToleranceSample(tolerance=2)
        assert surface_intervals(_surface(), sampling=tight)[0] > \
            surface_intervals(_surface(), sampling=loose)[0]

    def test_no_sampling_at_all_takes_the_default(self):
        assert surface_intervals(_surface()) == (
            int(DEFAULT_STEP), int(DEFAULT_STEP))

    def test_a_wider_knot_range_gets_more_samples(self):
        wide = [0, 0, 0, 0, 4, 4, 4, 4]
        assert surface_intervals(
            _surface(uKnot=wide, vKnot=wide), u_step=4, v_step=4) == (16, 16)


class TestAnUntrimmedSurface:
    def test_the_lattice_is_the_rate_by_the_rate(self):
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        assert t.vertex_count == 25            # 5 by 5 points
        assert t.triangle_count == 32          # two per quad of a 4 by 4 lattice

    def test_the_triangle_count_follows_the_rate(self):
        counts = {
            step: tessellate_surface(_surface(), u_step=step, v_step=step).triangle_count
            for step in (4, 8, 16, 30)
        }
        assert counts == {4: 32, 8: 128, 16: 512, 30: 1800}

    def test_a_plane_comes_back_flat(self):
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        assert np.allclose(t.positions[:, 2], 0.0)

    def test_the_normal_is_the_v_by_u_cross_product(self):
        """x follows u and y follows v, so the normal points along -z."""
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        assert np.allclose(t.normals, (0.0, 0.0, -1.0))

    def test_the_winding_agrees_with_the_normal(self):
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        a, b, c = t.positions[t.indices[0]]
        e1, e2 = b - a, c - a
        assert e1[0] * e2[1] - e1[1] * e2[0] < 0      # clockwise seen from +z

    def test_texcoords_run_u_then_v(self):
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        assert np.corrcoef(t.texcoords[:, 0], t.positions[:, 0])[0, 1] == pytest.approx(1.0)
        assert np.corrcoef(t.texcoords[:, 1], t.positions[:, 1])[0, 1] == pytest.approx(1.0)

    def test_texcoords_span_the_unit_square(self):
        t = tessellate_surface(_surface(), u_step=4, v_step=4)
        assert t.texcoords.min() == pytest.approx(0.0)
        assert t.texcoords.max() == pytest.approx(1.0)

    def test_every_index_addresses_a_vertex(self):
        t = tessellate_surface(_surface(), u_step=6, v_step=6)
        assert t.indices.min() >= 0
        assert t.indices.max() < t.vertex_count

    def test_the_domain_is_covered_once(self):
        assert _area(tessellate_surface(_surface(), u_step=16, v_step=16)) == \
            pytest.approx(9.0)


class TestColours:
    def _coloured(self, **kw):
        colors = [[x / 3.0, y / 3.0, 0.5] for y in range(4) for x in range(4)]
        return tessellate_surface(_surface(color=colors), **kw)

    def test_a_colour_per_vertex(self):
        t = self._coloured(u_step=4, v_step=4)
        assert len(t.colors) == t.vertex_count

    def test_they_are_opaque(self):
        t = self._coloured(u_step=4, v_step=4)
        assert np.allclose(t.colors[:, 3], 1.0)

    def test_a_corner_keeps_its_control_colour(self):
        """A clamped surface interpolates its corner control points."""
        t = self._coloured(u_step=4, v_step=4)
        assert np.allclose(t.colors[0], (0.0, 0.0, 0.5, 1.0))

    def test_they_interpolate_across_the_surface(self):
        t = self._coloured(u_step=8, v_step=8)
        assert t.colors[:, 0].min() < t.colors[:, 0].max()

    def test_no_colour_field_gives_no_colours(self):
        assert tessellate_surface(_surface(), u_step=4, v_step=4).colors is None

    def test_a_mismatched_colour_count_is_ignored(self, caplog):
        t = tessellate_surface(_surface(color=[[1, 0, 0]]), u_step=4, v_step=4)
        assert t.colors is None
        assert any('colour' in r.message for r in caplog.records)


class TestWeights:
    """The rational in NURBS: the ``weight`` field shapes the surface."""

    _RING = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1),
             (1, -1), (1, 0)]
    _U_KNOT = [0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1]

    def _cylinder(self, weighted):
        root = np.sqrt(2) / 2
        control = np.array([[x, y, z] for x, y in self._RING
                            for z in (0.0, 1.0)])
        # controlPoint is v-major: v (the two rings) varies slowest, u fastest.
        control = control.reshape(9, 2, 3).swapaxes(0, 1).reshape(-1, 3)
        weights = np.array([w for _ in range(2) for w in
                            (1, root, 1, root, 1, root, 1, root, 1)])
        return nurbs.NurbsSurface(
            controlPoint=control, uDimension=9, vDimension=2,
            uKnot=self._U_KNOT, vKnot=[0, 0, 1, 1],
            weight=weights if weighted else [],
        )

    def test_a_weighted_cylinder_is_exactly_round(self):
        t = tessellate_surface(self._cylinder(True), u_step=32, v_step=1)
        radii = np.linalg.norm(t.positions[:, :2], axis=1)
        assert np.allclose(radii, 1.0, atol=1e-5)

    def test_without_weights_it_is_only_approximately_round(self):
        t = tessellate_surface(self._cylinder(False), u_step=32, v_step=1)
        radii = np.linalg.norm(t.positions[:, :2], axis=1)
        assert radii.max() > 1.02

    def test_a_linear_direction_still_has_normals(self):
        """The cylinder is degree 1 up its length, and has to shade."""
        t = tessellate_surface(self._cylinder(True), u_step=32, v_step=1)
        assert np.allclose(np.linalg.norm(t.normals, axis=1), 1.0)
        assert np.allclose(t.normals[:, 2], 0.0)

    def test_a_mismatched_weight_count_is_ignored(self, caplog):
        t = tessellate_surface(_surface(weight=[1.0, 2.0]), u_step=4, v_step=4)
        assert t.triangle_count == 32
        assert any('weight' in r.message for r in caplog.records)


class TestTrimming:
    """A trimming loop keeps what lies to its left."""

    def test_a_counter_clockwise_loop_keeps_its_inside(self):
        t = tessellate_surface(_surface(), trimming_contours=_rings(_CCW),
                               u_step=16, v_step=16)
        assert _area(t) == pytest.approx(5.76, abs=0.01)   # 0.8 x 0.8 of 3 x 3

    def test_a_clockwise_loop_encloses_nothing(self, caplog):
        t = tessellate_surface(_surface(), trimming_contours=_rings(_CW),
                               u_step=16, v_step=16)
        assert t.triangle_count == 0
        assert any('trimming' in r.message for r in caplog.records)

    def test_a_clockwise_loop_inside_one_is_a_hole(self):
        t = tessellate_surface(_surface(), trimming_contours=_rings(_CCW, _INNER_CW),
                               u_step=16, v_step=16)
        assert _area(t) == pytest.approx(4.95, abs=0.01)   # the square less the hole

    def test_a_trimmed_surface_is_still_the_same_surface(self):
        t = tessellate_surface(_surface(), trimming_contours=_rings(_CCW),
                               u_step=16, v_step=16)
        assert np.allclose(t.positions[:, 2], 0.0)
        assert np.allclose(t.normals, (0.0, 0.0, -1.0))

    def test_it_is_sampled_as_finely_as_an_untrimmed_one(self):
        """Refinement follows the sampling rate, not just the outline's corners."""
        coarse = tessellate_surface(_surface(), trimming_contours=_rings(_CCW),
                                    u_step=4, v_step=4)
        fine = tessellate_surface(_surface(), trimming_contours=_rings(_CCW),
                                  u_step=24, v_step=24)
        assert fine.triangle_count > 8 * coarse.triangle_count

    def test_texcoords_follow_the_parameters(self):
        t = tessellate_surface(_surface(), trimming_contours=_rings(_CCW),
                               u_step=16, v_step=16)
        assert np.corrcoef(t.texcoords[:, 0], t.positions[:, 0])[0, 1] == \
            pytest.approx(1.0)

    def test_a_curved_trim_cuts_a_curved_hole(self):
        """The redbook trim: a NURBS curve joined to a polyline, as one loop.

        The loop runs clockwise inside a counter-clockwise boundary, so what it
        encloses is cut away.
        """
        outer = Contour2D(children=[
            Polyline2D(point=[[0, 0], [1, 0], [1, 1], [0, 1]])])
        hole = Contour2D(children=[
            NurbsCurve2D(
                knot=_KNOT,
                controlPoint=[[0.25, 0.5], [0.25, 0.75], [0.75, 0.75], [0.75, 0.5]]),
            Polyline2D(point=[[0.75, 0.5], [0.5, 0.25], [0.25, 0.5]]),
        ])
        whole = tessellate_surface(_surface(), u_step=16, v_step=16)
        t = tessellate_surface(_surface(), trimming_contours=[outer, hole],
                               u_step=16, v_step=16)
        assert t.triangle_count > 0
        assert 0 < _area(t) < _area(whole)

    def test_an_empty_contour_leaves_the_surface_whole(self):
        whole = tessellate_surface(_surface(), u_step=8, v_step=8)
        t = tessellate_surface(_surface(), trimming_contours=[Contour2D()],
                               u_step=8, v_step=8)
        assert t.triangle_count == whole.triangle_count

    def test_colours_survive_trimming(self):
        colors = [[x / 3.0, y / 3.0, 0.5] for y in range(4) for x in range(4)]
        t = tessellate_surface(_surface(color=colors),
                               trimming_contours=_rings(_CCW), u_step=8, v_step=8)
        assert len(t.colors) == t.vertex_count
        assert np.allclose(t.colors[:, 3], 1.0)


class TestBadSurfaces:
    def test_a_control_net_of_the_wrong_size_is_refused(self):
        with pytest.raises(NurbsError):
            tessellate_surface(_surface(uDimension=5))

    def test_a_knot_vector_that_implies_no_degree_is_refused(self):
        with pytest.raises(NurbsError):
            tessellate_surface(_surface(uKnot=[0, 0, 0, 0, 1]))

    def test_a_node_that_cannot_be_tessellated_does_not_raise_through_render(self):
        """The node logs and draws nothing rather than taking the frame down."""
        assert _surface(uDimension=5)._build_geometry() is None


class TestInterleaving:
    def test_normal_then_position_without_colours(self):
        t = tessellate_surface(_surface(), u_step=2, v_step=2)
        rows = interleave(t)
        assert rows.shape == (t.vertex_count, 6)
        assert np.allclose(rows[:, :3], t.normals)
        assert np.allclose(rows[:, 3:], t.positions)

    def test_colour_then_normal_then_position(self):
        colors = [[x / 3.0, y / 3.0, 0.5] for y in range(4) for x in range(4)]
        t = tessellate_surface(_surface(color=colors), u_step=2, v_step=2)
        rows = interleave(t)
        assert rows.shape == (t.vertex_count, 10)
        assert np.allclose(rows[:, :4], t.colors)
        assert np.allclose(rows[:, 4:7], t.normals)
        assert np.allclose(rows[:, 7:], t.positions)

    def test_it_is_float32(self):
        assert interleave(tessellate_surface(_surface(), u_step=2, v_step=2)).dtype \
            == np.float32


class TestTheTessellationItself:
    def test_it_counts_what_it_holds(self):
        t = SurfaceTessellation(
            positions=np.zeros((4, 3), np.float32),
            normals=np.zeros((4, 3), np.float32),
            texcoords=np.zeros((4, 2), np.float32),
            colors=None,
            indices=np.zeros((2, 3), np.uint32),
        )
        assert (t.vertex_count, t.triangle_count, t.index_count) == (4, 2, 6)


class TestTrimPrimitives:
    def test_a_polyline_is_its_own_points(self):
        assert np.allclose(Polyline2D(point=_CCW).points(), _CCW)

    def test_a_curve_is_evaluated_to_points(self):
        curve = NurbsCurve2D(
            knot=_KNOT, controlPoint=[[0, 0], [0, 1], [1, 1], [1, 0]])
        points = curve.points(steps=9)
        assert points.shape == (9, 2)
        assert np.allclose(points[0], (0, 0))       # clamped: reaches its ends
        assert np.allclose(points[-1], (1, 0))

    def test_a_curve_honours_its_tessellation_field(self):
        curve = NurbsCurve2D(
            knot=_KNOT, controlPoint=[[0, 0], [0, 1], [1, 1], [1, 0]],
            tessellation=5)
        assert len(curve.points()) == 5

    def test_a_curve_with_too_few_points_gives_none(self):
        assert len(NurbsCurve2D(knot=[], controlPoint=[]).points()) == 0

    def test_children_join_end_to_end(self):
        loop = Contour2D(children=[
            Polyline2D(point=[[0, 0], [1, 0]]),
            Polyline2D(point=[[1, 0], [1, 1]]),      # repeats the shared corner
        ])
        assert np.allclose(loop.contour(), [[0, 0], [1, 0], [1, 1]])

    def test_a_repeated_first_point_closes_rather_than_doubles(self):
        loop = Contour2D(children=[Polyline2D(point=_CCW + [_CCW[0]])])
        assert len(loop.contour()) == len(_CCW)

    def test_a_contour_of_nothing_is_empty(self):
        assert Contour2D().contour().shape == (0, 2)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
