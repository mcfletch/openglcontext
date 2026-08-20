"""Water that runs downhill: a surface swept along a path.

A lake is one flat plane and a river is not, so a sheet at a level cannot be a
river. This is the same wave field swept along a course at a width and a height
per point -- which is what the channel a world routes already knows.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.water.surface import (
    CHOPPY,
    FLOWING,
    STILL,
    water_glints,
    water_ribbon,
)


def _straight(points=9, length=80.0, drop=8.0):
    """A course running east and falling as it goes."""
    x = np.linspace(0.0, length, points)
    z = np.zeros_like(x)
    y = np.linspace(drop, 0.0, points)
    return np.stack([x, y, z], axis=-1)


class TestWhereItRuns:
    def test_it_follows_the_course_it_was_given(self) -> None:
        course = _straight()
        mesh = water_ribbon(course, width=6.0)
        points = np.asarray(mesh.positions)
        assert points[:, 0].min() == pytest.approx(0.0, abs=0.5)
        assert points[:, 0].max() == pytest.approx(80.0, abs=0.5)

    def test_it_runs_downhill_with_it(self) -> None:
        """The whole reason a sheet cannot be a river."""
        course = _straight()
        points = np.asarray(water_ribbon(course, width=6.0).positions)
        upstream = points[points[:, 0] < 10.0][:, 1].mean()
        downstream = points[points[:, 0] > 70.0][:, 1].mean()
        assert upstream > downstream + 5.0

    def test_it_is_as_wide_as_it_was_told(self) -> None:
        course = _straight()
        points = np.asarray(water_ribbon(course, width=6.0).positions)
        assert np.ptp(points[:, 2]) == pytest.approx(6.0, abs=0.2)

    def test_it_can_widen_as_it_goes(self) -> None:
        """A river carrying more is wider, and the width is per point for it."""
        course = _straight()
        widths = np.linspace(2.0, 20.0, len(course))
        points = np.asarray(water_ribbon(course, width=widths).positions)
        near = points[points[:, 0] < 5.0]
        far = points[points[:, 0] > 75.0]
        assert np.ptp(far[:, 2]) > np.ptp(near[:, 2]) * 3.0

    def test_it_turns_with_the_course(self) -> None:
        """The surface lies across the flow, so a bend is banked in plan and
        not a ribbon sticking out sideways."""
        course = np.array([[0.0, 0.0, 0.0], [40.0, 0.0, 0.0],
                           [40.0, 0.0, 40.0]])
        points = np.asarray(water_ribbon(course, width=8.0).positions)
        # At the far end the course runs north, so the surface spreads in x.
        far = points[points[:, 2] > 35.0]
        assert np.ptp(far[:, 0]) > 6.0


class TestWhatItIsMadeOf:
    def test_every_vertex_has_a_normal(self) -> None:
        mesh = water_ribbon(_straight(), width=6.0)
        assert len(mesh.normals) == len(mesh.positions)

    def test_it_is_wound_into_triangles(self) -> None:
        mesh = water_ribbon(_straight(), width=6.0)
        assert len(mesh.indices) % 3 == 0
        assert len(mesh.indices) > 0

    def test_a_flowing_style_moves_it(self) -> None:
        course = _straight()
        now = np.asarray(water_ribbon(course, width=6.0, style=CHOPPY,
                                      when=0.0).positions)
        later = np.asarray(water_ribbon(course, width=6.0, style=CHOPPY,
                                        when=1.0).positions)
        assert not np.allclose(now[:, 1], later[:, 1])

    def test_still_water_in_a_channel_stays_where_it_is(self) -> None:
        course = _straight()
        now = np.asarray(water_ribbon(course, width=6.0, style=STILL,
                                      when=0.0).positions)
        later = np.asarray(water_ribbon(course, width=6.0, style=STILL,
                                        when=3.0).positions)
        assert np.allclose(now, later)

    def test_the_crests_run_along_the_river(self) -> None:
        """Not across it: a river whose waves ran sideways would read as surf."""
        course = _straight(drop=0.0)
        mesh = water_ribbon(course, width=6.0, style=FLOWING, when=0.4)
        heights = np.asarray(mesh.positions)[:, 1]
        # Across the ribbon the height barely changes; along it, it does.
        across = np.asarray(mesh.positions)[:, 2]
        along = np.asarray(mesh.positions)[:, 0]
        assert np.std(heights[np.argsort(along)][:6]) \
            < np.std(heights) + 1e-9


class TestWhatItRefuses:
    def test_a_course_of_one_point_is_no_river(self) -> None:
        mesh = water_ribbon(np.array([[0.0, 0.0, 0.0]]), width=6.0)
        assert mesh is None

    def test_an_empty_course_is_no_river(self) -> None:
        assert water_ribbon(np.zeros((0, 3)), width=6.0) is None


class TestWaterFromFarOff:
    """A river a kilometre away is not a ribbon: it is the sun catching it
    here and there between whatever is in the way. A full surface at that
    range costs a tile's whole budget to draw a line two pixels wide."""

    def test_it_puts_glints_along_the_course(self) -> None:
        mesh = water_glints(_straight(length=400.0, points=41), width=8.0,
                            spacing=50.0)
        assert mesh is not None
        assert len(mesh.positions) >= 4 * 6

    def test_they_are_spread_along_it(self) -> None:
        mesh = water_glints(_straight(length=400.0, points=41), width=8.0,
                            spacing=50.0)
        points = np.asarray(mesh.positions)
        assert np.ptp(points[:, 0]) > 300.0

    def test_a_wider_spacing_makes_fewer(self) -> None:
        near = water_glints(_straight(length=400.0, points=41), width=8.0,
                            spacing=25.0)
        far = water_glints(_straight(length=400.0, points=41), width=8.0,
                           spacing=200.0)
        assert len(far.positions) < len(near.positions)

    def test_they_sit_on_the_water_not_beside_it(self) -> None:
        course = _straight(length=400.0, points=41, drop=0.0)
        points = np.asarray(water_glints(course, width=8.0,
                                         spacing=50.0).positions)
        assert np.abs(points[:, 2]).max() <= 8.0

    def test_they_follow_the_water_downhill(self) -> None:
        course = _straight(length=400.0, points=41, drop=40.0)
        points = np.asarray(water_glints(course, width=8.0,
                                         spacing=50.0).positions)
        near = points[points[:, 0] < 100.0][:, 1].mean()
        far = points[points[:, 0] > 300.0][:, 1].mean()
        assert near > far + 20.0

    def test_the_same_river_glints_in_the_same_places(self) -> None:
        """A world baked twice is the same world."""
        course = _straight(length=400.0, points=41)
        assert np.array_equal(
            np.asarray(water_glints(course, width=8.0, spacing=50.0).positions),
            np.asarray(water_glints(course, width=8.0, spacing=50.0).positions))

    def test_a_course_too_short_to_glint_gives_nothing(self) -> None:
        assert water_glints(np.zeros((1, 3)), width=8.0, spacing=50.0) is None

    def test_they_are_wound_into_triangles(self) -> None:
        mesh = water_glints(_straight(length=400.0, points=41), width=8.0,
                            spacing=50.0)
        assert len(mesh.indices) % 3 == 0
