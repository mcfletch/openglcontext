"""The level-of-detail quality measure, and the distances it yields.

The metrics take images and return numbers, so most of this needs no window.
The one class that does need GL renders a mesh twice and is asked whether the
difference it reports is the difference that is there.
"""

import numpy as np
import pytest

from OpenGLContext.meshlod import chain as meshchain
from OpenGLContext.meshlod import quality


def _image(value, size=8):
    return np.full((size, size, 3), value, dtype=np.uint8)


def _tetrahedron():
    """A shape coarse enough that its own edges are several pixels apart."""
    positions = np.asarray(
        [(1.0, 1.0, 1.0), (1.0, -1.0, -1.0), (-1.0, 1.0, -1.0), (-1.0, -1.0, 1.0)],
        dtype="f4",
    )
    indices = np.asarray([0, 1, 2, 0, 3, 1, 0, 2, 3, 1, 3, 2], dtype=np.uint32)
    normals = positions / np.linalg.norm(positions, axis=1)[:, None]
    return positions, normals.astype("f4"), indices


class TestDrawingTheEdges:
    """``edges=True`` puts the triangle structure on top of the shading.

    A level of detail is a triangle count, and a picture of the shaded surface
    says nothing about where those triangles went. Drawing the wireframe over
    the fill is what makes a gallery of levels legible.
    """

    def test_the_edges_darken_the_inside_without_moving_the_outline(self, gl_context):
        positions, normals, indices = _tetrahedron()
        with quality.LODProbe(size=96) as probe:
            plain = probe.render(positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0))
            wired = probe.render(positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0), edges=True)
        covered = quality.silhouette(plain)
        assert np.any(covered), "the probe drew nothing to put edges on"
        # The edges are drawn on the object, not around it: every pixel the
        # shaded render covers is still covered, and the only pixels gained are
        # the rim a rasterised line puts half outside the triangle it bounds.
        gained = quality.silhouette(wired) & ~covered
        assert np.all(quality.silhouette(wired)[covered])
        assert np.count_nonzero(gained) < 0.1 * np.count_nonzero(covered)
        # And inside it, the wireframe can only take light away.
        assert int(wired[covered].sum()) < int(plain[covered].sum())

    def test_a_plain_render_is_unchanged_by_the_option_existing(self, gl_context):
        positions, normals, indices = _tetrahedron()
        with quality.LODProbe(size=64) as probe:
            once = probe.render(positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0))
            again = probe.render(
                positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0), edges=False
            )
        assert np.array_equal(once, again)


class TestWhatALevelCostsToDraw:
    """A level's triangle count is not what a renderer pays; drawing it is."""

    def test_it_reports_what_it_drew(self, gl_context):
        positions, normals, indices = _tetrahedron()
        with quality.LODProbe(size=64) as probe:
            cost = probe.frame_cost(
                positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0), frames=8, warmup=2
            )
        assert cost.frames == 8
        assert cost.triangles == len(indices) // 3
        assert cost.median_ms > 0.0
        assert cost.fps == pytest.approx(1000.0 / cost.median_ms)

    def test_it_leaves_the_picture_the_plain_render_would_have(self, gl_context):
        """The number comes from drawing the mesh, not from counting it."""
        positions, normals, indices = _tetrahedron()
        with quality.LODProbe(size=64) as probe:
            wanted = probe.render(positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0))
            probe.frame_cost(
                positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0), frames=4, warmup=1
            )
            drawn = probe.read()
        assert np.array_equal(drawn, wanted)

    def test_it_refuses_to_measure_nothing(self, gl_context):
        positions, normals, indices = _tetrahedron()
        with quality.LODProbe(size=32) as probe:
            with pytest.raises(ValueError, match="frames"):
                probe.frame_cost(positions, normals, indices, 4.0, 1.8, (0.0, 0.0, 0.0), frames=0)


class TestSilhouette:
    def test_the_background_is_not_the_object(self):
        picture = _image(0)
        picture[2:5, 2:5] = 200
        mask = quality.silhouette(picture)
        assert np.count_nonzero(mask) == 9

    def test_a_dark_object_still_counts(self):
        """Ambient keeps a face turned away above the background, on purpose."""
        picture = _image(0)
        picture[0, 0] = 25
        assert np.count_nonzero(quality.silhouette(picture)) == 1


class TestObjectPop:
    def test_a_mesh_does_not_pop_against_itself(self):
        picture = _image(0)
        picture[2:6, 2:6] = 180
        assert quality.object_pop(picture, picture) == 0.0

    def test_the_denominator_is_the_object_not_the_frame(self):
        """Nine pixels of object, all changed: that is a complete pop."""
        before, after = _image(0), _image(0)
        before[1:4, 1:4] = 200
        after[5:8, 5:8] = 200
        assert quality.object_pop(before, after) == pytest.approx(1.0)

    def test_geometry_that_appears_counts_as_much_as_geometry_that_goes(self):
        before, after = _image(0), _image(0)
        before[0:2, 0:2] = 200
        after[0:2, 0:2] = 200
        after[4:6, 4:6] = 200
        assert quality.object_pop(before, after) == pytest.approx(0.5)

    def test_a_change_under_the_threshold_is_not_a_pop(self):
        before = _image(100)
        after = _image(100 + quality.CHANNEL_DELTA - 1)
        assert quality.object_pop(before, after) == 0.0

    def test_a_change_over_the_threshold_is(self):
        before = _image(100)
        after = _image(100 + quality.CHANNEL_DELTA + 1)
        assert quality.object_pop(before, after) == pytest.approx(1.0)

    def test_an_empty_frame_has_nothing_to_pop(self):
        assert quality.object_pop(_image(0), _image(0)) == 0.0


class TestSafeDistance:
    #: A level looks worse the closer it is, so a sweep falls as it goes out.
    DISTANCES = [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_it_finds_where_the_pop_falls_under_budget(self):
        pops = [0.40, 0.20, 0.05, 0.01, 0.00]
        found = quality.safe_distance(self.DISTANCES, pops, budget=0.02)
        assert 4.0 < found < 8.0

    def test_it_interpolates_rather_than_snapping_to_a_sample(self):
        """Halfway between the straddling samples, for a budget halfway between."""
        found = quality.safe_distance([1.0, 2.0], [0.10, 0.0], budget=0.05)
        assert found == pytest.approx(1.5)

    def test_a_level_good_everywhere_is_safe_from_the_start(self):
        found = quality.safe_distance(self.DISTANCES, [0.001] * 5, budget=0.02)
        assert found == 1.0

    def test_a_level_bad_everywhere_is_never_safe(self):
        found = quality.safe_distance(self.DISTANCES, [0.9] * 5, budget=0.02)
        assert found == float("inf")

    def test_a_flat_run_takes_the_further_sample(self):
        found = quality.safe_distance([1.0, 2.0], [0.02, 0.02], budget=0.02)
        assert found == 1.0


class TestBoundingSphere:
    def test_it_holds_every_point(self):
        points = np.asarray([(-1.0, 0, 0), (3.0, 0, 0), (0, 2.0, 0)], dtype="f4")
        centre, radius = meshchain.bounding_sphere(points)
        assert np.all(np.linalg.norm(points - centre, axis=1) <= radius + 1e-6)

    def test_a_dense_side_does_not_drag_the_centre(self):
        """Box centre, not point average: a lopsided sampling must not tilt it."""
        crowd = np.zeros((500, 3), dtype="f4")
        crowd[:, 0] = -1.0
        points = np.concatenate([crowd, np.asarray([(1.0, 0, 0)], dtype="f4")])
        centre, _radius = meshchain.bounding_sphere(points)
        assert centre[0] == pytest.approx(0.0)

    def test_an_empty_mesh_has_no_extent(self):
        centre, radius = meshchain.bounding_sphere(np.zeros((0, 3), dtype="f4"))
        assert radius == 0.0
        assert np.all(centre == 0.0)


class TestSafeDistanceIsNotFooledByTheNearField:
    """A sweep is not monotone at the near end.

    Close enough and the camera is inside the object: nothing is on screen, both
    renders are empty, and the pop reads zero. Taken as "safe" that would report
    the coarsest level as usable from touching distance, which is the opposite of
    the truth. The answer has to be the distance beyond which the level stays
    within budget, found from the far end inwards.
    """

    DISTANCES = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

    def test_zeroes_at_the_near_end_are_not_a_pass(self):
        pops = [0.0, 0.0, 0.50, 0.30, 0.01, 0.0]
        found = quality.safe_distance(self.DISTANCES, pops, budget=0.02)
        assert 4.0 < found <= 8.0

    def test_a_level_that_is_only_good_far_away_says_so(self):
        pops = [0.60, 0.55, 0.40, 0.20, 0.05, 0.001]
        found = quality.safe_distance(self.DISTANCES, pops, budget=0.02)
        assert 8.0 < found <= 16.0

    def test_a_single_bad_sample_far_out_still_counts(self):
        """Something wrong at distance is wrong however good the near field is."""
        pops = [0.0, 0.0, 0.0, 0.0, 0.0, 0.9]
        assert quality.safe_distance(self.DISTANCES, pops, budget=0.02) == float("inf")


class TestPopBreakdown:
    """A pop has two causes and they call for different fixes.

    Geometry that moved changes the object's *outline*; normals that changed
    shade the same pixels differently. The first is fixed by keeping more
    triangles, the second by how the level's normals are built -- so a single
    number that mixes them says nothing about what to do.
    """

    def test_a_changed_outline_is_charged_to_the_silhouette(self):
        before, after = _image(0), _image(0)
        before[1:5, 1:5] = 200
        after[1:5, 1:7] = 200  # the same object, grown to the right
        outline, shading = quality.pop_breakdown(before, after)
        assert outline > 0.0
        assert shading == 0.0

    def test_a_changed_shading_is_charged_to_the_shading(self):
        before, after = _image(0), _image(0)
        before[1:5, 1:5] = 100
        after[1:5, 1:5] = 200  # the same outline, lit differently
        outline, shading = quality.pop_breakdown(before, after)
        assert outline == 0.0
        assert shading == pytest.approx(1.0)

    def test_the_two_together_are_the_whole_pop(self):
        before, after = _image(0), _image(0)
        before[1:5, 1:5] = 100
        after[1:5, 1:7] = 220
        outline, shading = quality.pop_breakdown(before, after)
        assert outline + shading == pytest.approx(quality.object_pop(before, after))

    def test_an_empty_frame_breaks_down_to_nothing(self):
        assert quality.pop_breakdown(_image(0), _image(0)) == (0.0, 0.0)
