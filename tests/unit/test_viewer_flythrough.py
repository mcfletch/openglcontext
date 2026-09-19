"""Walking the camera along the viewpoints a scene brought with it.

A recording of a scene that does not move is a picture with a file size, and
what to move along is already in most scenes: the cameras the author placed.
This is the arithmetic of where the camera is partway along that path -- no GL,
no scenegraph.
"""
import pytest

from OpenGLContext import quaternion
from OpenGLContext.viewer import flythrough


def facing(angle):
    return quaternion.fromXYZR(0.0, 1.0, 0.0, angle)


@pytest.fixture
def path():
    return [([0.0, 0.0, 0.0], facing(0.0)),
            ([10.0, 0.0, 0.0], facing(0.0)),
            ([10.0, 0.0, 10.0], facing(1.0))]


class TestEasing:
    def test_it_starts_and_ends_where_it_is_asked_to(self):
        assert flythrough.ease(0.0) == 0.0
        assert flythrough.ease(1.0) == 1.0

    def test_the_middle_is_the_middle(self):
        assert flythrough.ease(0.5) == pytest.approx(0.5)

    def test_it_starts_slowly(self):
        """A camera that begins at full speed reads as a cut."""
        assert flythrough.ease(0.1) < 0.1

    def test_it_ends_slowly(self):
        assert flythrough.ease(0.9) > 0.9

    def test_it_is_clamped(self):
        assert flythrough.ease(-1.0) == 0.0
        assert flythrough.ease(2.0) == 1.0


class TestWhichLegOfThePath:
    def test_the_start_is_the_first_leg(self):
        assert flythrough.segment_at(3, 0.0) == (0, 0.0)

    def test_halfway_along_two_legs_is_the_join(self):
        index, along = flythrough.segment_at(3, 0.5)

        assert (index, along) == pytest.approx((1, 0.0))

    def test_the_end_is_the_last_leg_complete(self):
        """Rather than the first point of a leg that does not exist."""
        index, along = flythrough.segment_at(3, 1.0)

        assert (index, along) == (1, 1.0)

    def test_one_waypoint_has_no_legs(self):
        assert flythrough.segment_at(1, 0.7) == (0, 0.0)


class TestWhereTheCameraIs:
    def test_it_starts_at_the_first_viewpoint(self, path):
        where, _facing = flythrough.pose_at(path, 0.0)

        assert list(where) == pytest.approx([0.0, 0.0, 0.0])

    def test_it_ends_at_the_last(self, path):
        where, _facing = flythrough.pose_at(path, 1.0)

        assert list(where) == pytest.approx([10.0, 0.0, 10.0])

    def test_it_passes_through_the_middle_one(self, path):
        where, _facing = flythrough.pose_at(path, 0.5)

        assert list(where) == pytest.approx([10.0, 0.0, 0.0])

    def test_it_moves_monotonically_along_the_path(self, path):
        travelled = [flythrough.pose_at(path, n / 20.0)[0][0] for n in range(11)]

        assert travelled == sorted(travelled)

    def test_it_turns_between_the_last_two(self, path):
        _where, half = flythrough.pose_at(path, 0.75, smooth=False)
        _where, whole = flythrough.pose_at(path, 1.0)

        assert half != whole

    def test_a_single_viewpoint_stays_put(self):
        only = [([1.0, 2.0, 3.0], facing(0.0))]

        where, _facing = flythrough.pose_at(only, 0.6)

        assert list(where) == pytest.approx([1.0, 2.0, 3.0])

    def test_no_viewpoints_is_refused(self):
        with pytest.raises(ValueError):
            flythrough.pose_at([], 0.5)

    def test_easing_does_not_move_the_ends(self, path):
        assert list(flythrough.pose_at(path, 0.0)[0]) == \
            pytest.approx(list(flythrough.pose_at(path, 0.0, smooth=False)[0]))


class TestReadingThePathOffAScene:
    class Viewpoint:
        def __init__(self, position, orientation):
            self.position = position
            self.orientation = orientation

    def test_each_viewpoint_becomes_a_pose(self):
        found = flythrough.poses_from([
            self.Viewpoint((0, 1, 2), (0, 1, 0, 0.0)),
            self.Viewpoint((3, 4, 5), (0, 1, 0, 1.5)),
        ])

        assert len(found) == 2
        assert list(found[1][0]) == pytest.approx([3.0, 4.0, 5.0])

    def test_the_path_is_in_the_order_the_scene_declared_them(self):
        found = flythrough.poses_from([
            self.Viewpoint((0, 0, 0), (0, 1, 0, 0.0)),
            self.Viewpoint((9, 0, 0), (0, 1, 0, 0.0)),
        ])

        assert list(found[0][0])[0] == 0.0 and list(found[1][0])[0] == 9.0
