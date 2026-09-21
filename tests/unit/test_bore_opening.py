"""Where a bore breaks the surface of the hill it runs through.

A tunnel is cut through a hill, and the hill is still a hill: the ground over
the bore is ground, and what has to come out of it is the *mouth* -- the
hillside standing where the portal's face stands, and nothing else.
:func:`~OpenGLContext.scenegraph.roadworks.bore_opening` is that shape, as the
``holes(x, z)`` a height field is cut with.

The ground here rises across the bore, so one straight line runs the whole way
from open cutting to buried hillside: under the road at the approach, across the
face at the mouth, over the top of it once the hill has closed above.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.road import RoadProfile
from OpenGLContext.scenegraph.roadworks import TunnelProfile, bore_opening

#: The bore runs along x at y=0, from the first of these to the last.
ENDS = (-50.0, 50.0)

#: The hillside: level with the road at x=-40 and climbing at 0.6.
def hillside(x, z):
    return 0.6 * (np.asarray(x, 'd') + 40.0) + 0.0 * np.asarray(z, 'd')


def line(points=21):
    x = np.linspace(ENDS[0], ENDS[1], points)
    return np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=-1)


def opening(**named):
    return bore_opening(line(), hillside, **named)


def face():
    """How wide and how tall the portal's face is, in metres."""
    tunnel = TunnelProfile()
    profile = RoadProfile()
    return (profile.on_structure().total_width / 2.0 + tunnel.margin
            + tunnel.portal_border,
            tunnel.clearance + tunnel.portal_border)


class TestTheMouthAndNothingElse:
    def test_the_hillside_over_the_bore_is_ground(self) -> None:
        """Ten metres in, the hill stands above the face: it is a hill."""
        assert not opening()(-10.0, 0.0)

    def test_the_mouth_is_open(self) -> None:
        _wide, tall = face()
        # Where the hillside has risen over the carriageway but not yet over
        # the face, the ground is standing in the portal.
        at = -40.0 + tall / 0.6 / 2.0
        assert 0.0 < hillside(at, 0.0) < tall
        assert opening()(at, 0.0)

    def test_the_cutting_the_road_runs_in_is_ground(self) -> None:
        """Before the portal the ground is under the road, and stays."""
        assert hillside(-45.0, 0.0) < 0.0
        assert not opening()(-45.0, 0.0)

    def test_the_hillside_beside_the_portal_is_ground(self) -> None:
        wide, _tall = face()
        at = -40.0 + 4.0
        assert opening()(at, 0.0)
        assert not opening()(at, wide + 0.5)

    def test_the_opening_is_the_shape_of_the_face(self) -> None:
        """Square across, since what stands there is a wall: at the edge of the
        face the ground goes as far up as it does in the middle."""
        wide, tall = face()
        found = opening()
        at = -40.0 + tall / 0.6 / 2.0
        assert found(at, 0.0)
        assert found(at, wide * 0.95)
        assert not found(at, wide * 1.05)

    def test_a_bore_the_hill_covers_all_the_way_is_never_open(self) -> None:
        deep = bore_opening(line(), lambda x, z: np.full(np.shape(x), 90.0))
        x = np.linspace(-60.0, 60.0, 41)
        assert not deep(x, np.zeros_like(x)).any()


class TestWhatItAnswersWith:
    def test_the_answer_is_the_shape_of_the_question(self) -> None:
        found = opening()
        x, z = np.meshgrid(np.linspace(-60.0, 60.0, 7), np.linspace(-20, 20, 5))
        assert np.shape(found(x, z)) == (5, 7)

    def test_it_is_a_mask_of_true_and_false(self) -> None:
        found = opening()(np.array([-45.0, -35.0, 0.0]), np.zeros(3))
        assert found.dtype == bool

    def test_nothing_within_reach_of_the_line_is_open(self) -> None:
        """A point well off the end of the bore is nowhere near it."""
        assert not opening()(-200.0, 0.0)


class TestTheApproachClearsTheRoadsOwnSpace:
    """The step from the cutting to the hillside is drawn between two samples,
    one under the road and one over the hill -- so it stands across the
    carriageway and no rule about heights takes it out. What does is clearing
    the road's own space on the run up to the face.
    """

    def road(self):
        """How wide the road's own surface is, verge to verge."""
        return RoadProfile().total_width / 2.0

    def test_the_carriageway_is_clear_before_the_face(self) -> None:
        """Ground under the road, which no height rule would touch."""
        before = ENDS[0] - 6.0
        assert hillside(before, 0.0) < 0.0
        assert not opening()(before, 0.0)
        assert opening(approach=12.0)(before, 0.0)

    def test_only_as_far_back_as_it_is_asked_for(self) -> None:
        assert not opening(approach=12.0)(ENDS[0] - 20.0, 0.0)

    def test_and_no_wider_than_the_road_itself(self) -> None:
        """Past the road nothing covers the hole, so nothing is cut."""
        paved = self.road()
        before = ENDS[0] - 6.0
        assert opening(approach=12.0)(before, paved - 0.5)
        assert not opening(approach=12.0)(before, paved + 0.5)

    def test_it_does_not_reach_back_into_the_hill(self) -> None:
        """In front of the face and nowhere else: the hill over the bore is a
        hill, and clearing the road's space through it is the old canyon."""
        assert not opening(approach=12.0)(-20.0, 0.0)


class TestTheInsetDrawsItBackInsideTheFace:
    """So the face stands in front of the edge of the cut rather than on it."""

    def test_an_inset_leaves_the_ground_at_the_edge_of_the_face(self) -> None:
        wide, _tall = face()
        at = -40.0 + 4.0
        assert opening()(at, wide - 0.1)
        assert not opening(inset=1.0)(at, wide - 0.1)

    def test_and_the_ground_at_the_top_of_it(self) -> None:
        _wide, tall = face()
        at = -40.0 + (tall - 0.2) / 0.6
        assert 0.0 < hillside(at, 0.0) < tall
        assert opening()(at, 0.0)
        assert not opening(inset=1.0)(at, 0.0)
