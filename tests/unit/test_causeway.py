"""A road carried over low ground on its own narrow embankment.

Where the alignment runs a few metres above the land -- a lake margin, a shallow
draw -- a bridge is more structure than the crossing needs and an earth
embankment battered out to the natural slope is a hillside the width of a field.
A causeway is the middle: fill only as wide as the road on it, walled at each
edge, with the ground left as it was found either side.

The wall is low on purpose. Everything the crossing is *for* -- the water, the
drop, the country beyond it -- is only there if the driver can see over it.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.road import RoadProfile
from OpenGLContext.scenegraph.roadworks import CausewayProfile, causeway_meshes

PROFILE = RoadProfile(lane_width=3.6, lanes=2, shoulder_width=0.7,
                      shoulder_drop=0.05, verge_width=1.0, verge_drop=0.35)


def _line(length=120.0, height=12.0, points=25):
    z = np.linspace(0.0, length, points)
    return np.stack([np.zeros(points), np.full(points, height), z], axis=-1)


def _ground(depth=6.0):
    def at(x, z):
        return np.zeros_like(np.asarray(z, 'd')) + (12.0 - depth)
    return at


#: Where the road surface is at its edge, which is what a wall stands on: the
#: crossfall puts that a little below the centreline the sweep is given.
EDGE = float(PROFILE.on_structure().section()[0, 1])


def _built(**named):
    named.setdefault('points', _line())
    named.setdefault('profile', PROFILE)
    named.setdefault('ground', _ground())
    return causeway_meshes(**named)


class TestWhatItIs:
    def test_it_has_a_body_and_a_wall(self) -> None:
        assert set(_built()) == {'body', 'wall'}

    def test_it_needs_a_line_to_run_along(self) -> None:
        with pytest.raises(ValueError):
            causeway_meshes(np.zeros((1, 3)))

    def test_without_ground_it_is_only_its_wall(self) -> None:
        assert set(causeway_meshes(_line(), PROFILE)) == {'wall'}

    def test_its_parts_are_drawable(self) -> None:
        for mesh in _built().values():
            assert len(mesh.positions) and len(mesh.indices)
            assert len(mesh.normals) == len(mesh.positions)


class TestTheDriverCanSeeOverIt:
    def test_the_wall_is_below_eye_height(self) -> None:
        """A seated driver's eye is about 1.2m over the road."""
        wall = _built()['wall']
        assert float(wall.positions[:, 1].max()) - (12.0 + EDGE) < 1.1

    def test_it_is_tall_enough_to_read_as_a_wall(self) -> None:
        assert float(_built()['wall'].positions[:, 1].max()) \
            - (12.0 + EDGE) > 0.5

    def test_a_caller_may_ask_for_a_different_one(self) -> None:
        low = _built(causeway=CausewayProfile(wall_height=0.4))
        assert float(low['wall'].positions[:, 1].max()) - (12.0 + EDGE) == \
            pytest.approx(0.4, abs=0.05)


class TestItIsBarelyWiderThanTheRoad:
    def test_the_wall_stands_at_the_edge_of_the_carried_road(self) -> None:
        carried = PROFILE.on_structure().total_width / 2.0
        assert float(_built()['wall'].positions[:, 0].max()) \
            == pytest.approx(carried, abs=0.01)

    def test_it_is_narrower_than_the_road_with_its_verges(self) -> None:
        assert float(_built()['wall'].positions[:, 0].max()) \
            < PROFILE.total_width / 2.0

    def test_the_fill_leans_out_only_a_little(self) -> None:
        """Six metres of fill, and the foot is within a metre of the top."""
        carried = PROFILE.on_structure().total_width / 2.0
        assert float(_built()['body'].positions[:, 0].max()) - carried < 1.0

    def test_a_deeper_crossing_has_a_wider_foot(self) -> None:
        shallow = _built(ground=_ground(2.0))['body']
        deep = _built(ground=_ground(14.0))['body']
        assert float(deep.positions[:, 0].max()) \
            > float(shallow.positions[:, 0].max())


class TestItReachesTheGround:
    def test_the_fill_goes_down_to_the_land(self) -> None:
        assert float(_built()['body'].positions[:, 1].min()) \
            == pytest.approx(6.0, abs=0.35)

    def test_it_follows_ground_that_is_not_level(self) -> None:
        def sloping(x, z):
            return 12.0 - np.asarray(z, 'd') * 0.05
        body = _built(ground=sloping)['body']
        low = body.positions[body.positions[:, 2] > 100.0][:, 1].min()
        high = body.positions[body.positions[:, 2] < 20.0][:, 1].min()
        assert float(high) - float(low) > 3.0

    def test_it_keeps_a_lip_where_the_road_meets_the_land(self) -> None:
        """Fill of no depth leaves the wall standing on nothing."""
        body = _built(ground=_ground(0.0))['body']
        assert 11.0 < float(body.positions[:, 1].min()) < 12.0

    def test_the_fill_is_never_above_the_road(self) -> None:
        assert float(_built()['body'].positions[:, 1].max()) <= 12.01


class TestItFollowsTheRoad:
    def test_it_runs_the_length_it_was_given(self) -> None:
        body = _built()['body']
        assert float(body.positions[:, 2].max()) == pytest.approx(120.0, abs=0.1)

    def test_it_leans_with_a_bend(self) -> None:
        angle = np.linspace(0.0, np.pi / 2.0, 30)
        line = np.stack([np.cos(angle) * 80.0, np.full(30, 12.0),
                         np.sin(angle) * 80.0], axis=-1)
        wall = _built(points=line)['wall']
        radius = np.hypot(wall.positions[:, 0], wall.positions[:, 2])
        assert float(radius.min()) > 70.0 and float(radius.max()) < 90.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
