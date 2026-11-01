"""Props a car can hit, held in the physics world only while they are near.

A world's boulders are hundreds of bodies and a car touches one of them at a
time; the collision broadphase pays for every one it is holding. So the same
rule the ground follows applies here: what is within reach is in the world, and
what is not is taken out again.

A prop's body comes from its own measurements rather than from its mesh. The
geometry is level-of-detail geometry that arrives and leaves with a tile, and a
collider that came and went with it would be a rock a car drives through at the
moment the tile behind it swaps.
"""
import numpy as np
import pytest

from OpenGLContext.physics.body import Body
from OpenGLContext.physics.props import PropSource
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.scenegraph.props import Prop
from OpenGLContext.testing import physics as physics_testing
from tests.unit._streamed import Streamed


def _scattered(count=40, spacing=25.0):
    return [Prop(kind='rock', position=(index * spacing, 0.0, 0.0),
                 radius=1.0, height=1.4)
            for index in range(count)]


def _served(props, **named):
    """``props`` as a source of a service of its own, not yet asked."""
    return Streamed(PropSource(props, **named))


def _stood(props, **named):
    """``props`` as a source of a service of its own, asked once with the focus at the origin."""
    served = _served(props, **named)
    served.update((0.0, 0.0, 0.0))
    return served


def _held(served):
    """How many bodies the world is carrying."""
    return served.physics.counts.bodies


def _body(served, index=0):
    """The body of prop ``index``."""
    return served.handle.bodies[index]


def _at(served, index=0):
    """Where the world holds the body of prop ``index``."""
    return physics_testing.world_position(served.physics, _body(served, index))


def _ground(served):
    """A floor under the props, its top at height 0."""
    return served.physics.add_static(None, Proxy.box((400.0, 2.0, 400.0)),
                                     translation=(0.0, -1.0, 0.0))


def _run(served, seconds):
    for _ in range(int(round(seconds * 60.0))):
        served.physics.frame(1.0 / 60.0)


class TestASource:
    """:class:`PropSource` makes the bodies through a physics service."""

    def test_each_prop_within_reach_is_a_body_of_the_service(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        hit = props.physics.raycast((0.0, 20.0, 0.0), (0.0, -1.0, 0.0), 40.0)
        assert isinstance(hit.body, Body)
        assert hit.point[1] == pytest.approx(1.4, abs=0.01)
        assert _held(props) == len(props.standing)

    def test_it_answers_what_changed(self) -> None:
        source = PropSource(_scattered(), reach=60.0)
        first = source.update((0.0, 0.0, 0.0))
        assert [one[0] for one in first.add] == [0, 1, 2]
        assert not source.update((1.0, 0.0, 1.0)).add
        later = source.update((500.0, 0.0, 0.0))
        assert sorted(later.remove) == [0, 1, 2]
        assert all(abs(one.position[0] - 500.0) <= 60.0 for one in source.standing)

    def test_moving_less_than_settled_asks_nothing(self) -> None:
        source = PropSource(_scattered(), reach=60.0, settled=20.0)
        source.update((0.0, 0.0, 0.0))
        moved = source.update((19.0, 0.0, 0.0))
        assert not moved.add and not moved.remove

    def test_props_of_one_size_share_a_shape(self) -> None:
        source = PropSource(_scattered(), reach=1000.0)
        added = source.update((0.0, 0.0, 0.0)).add
        assert len({id(one[1]) for one in added}) == 1

    def test_clearing_lets_go_of_everything(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        props.clear()
        assert props.standing == []
        assert _held(props) == 0
        assert props.source.update((0.0, 0.0, 0.0)).add

    def test_a_turned_prop_stands_turned_by_its_yaw(self) -> None:
        stones = [Prop(kind='stone', position=(3.0, 1.0, 2.0), radius=0.3, height=1.0,
                       shape='dome', yaw=0.7),
                  Prop(kind='rock', position=(-4.0, 2.0, 1.0), radius=1.2, height=2.0, yaw=1.1)]
        served = _stood(stones)
        poses = served.physics.poses([_body(served, 0), _body(served, 1)])
        for row, prop in enumerate(stones):
            half = prop.yaw / 2.0
            assert np.allclose(np.abs(poses.orientation[row]),
                               np.abs((0.0, np.sin(half), 0.0, np.cos(half))), atol=1e-6)
        assert [_body(served, row).proxy.kind for row in range(2)] == ['sphere', 'box']


class TestWhatIsHeld:
    def test_nothing_before_the_first_update(self) -> None:
        props = _served(_scattered())
        assert _held(props) == 0 and props.standing == []

    def test_the_ones_within_reach_are_stood_up(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        assert 2 <= _held(props) <= 6
        assert _held(props) == len(props.standing)

    def test_the_far_ones_are_not(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        assert _held(props) < 40

    def test_walking_along_brings_the_next_ones(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        props.update((500.0, 0.0, 0.0))
        assert props.standing
        assert all(abs(one.position[0] - 500.0) <= 60.0
                   for one in props.standing)

    def test_and_takes_away_the_ones_behind(self) -> None:
        """A lap holds what a lap can reach, not everything it has passed."""
        props = _served(_scattered(), reach=60.0)
        for along in range(0, 1000, 40):
            props.update((float(along), 0.0, 0.0))
        assert _held(props) <= 6
        assert not any(one.position[0] < 400.0 for one in props.standing)

    def test_standing_still_changes_nothing(self) -> None:
        props = _stood(_scattered(), reach=60.0)
        before = list(props.standing)
        props.update((1.0, 0.0, 1.0))
        assert list(props.standing) == before

    def test_a_world_with_no_props_is_not_an_error(self) -> None:
        assert _held(_stood([])) == 0


class TestWhatABodyIs:
    def test_it_is_where_the_prop_is(self) -> None:
        props = _stood([Prop(kind='rock', position=(4.0, 7.0, -2.0), radius=1.0, height=2.0)])
        at = _at(props)
        assert float(at[0]) == pytest.approx(4.0, abs=0.01)
        assert float(at[2]) == pytest.approx(-2.0, abs=0.01)

    def test_its_middle_is_half_its_height_up(self) -> None:
        """A prop's position is its foot; a box's is its centre."""
        props = _stood([Prop(kind='rock', position=(0.0, 10.0, 0.0), radius=1.0, height=2.0)])
        assert float(_at(props)[1]) == pytest.approx(11.0, abs=0.01)

    def test_it_does_not_move(self) -> None:
        props = _stood([Prop(kind='rock', position=(0.0, 0.0, 0.0))])
        before = _at(props).copy()
        _run(props, 0.5)
        assert np.allclose(_at(props), before)

    def test_a_car_stops_against_one(self) -> None:
        """The point of the whole thing."""
        props = _stood([Prop(kind='rock', position=(0.0, 0.0, 8.0), radius=2.0, height=3.0)])
        _ground(props)
        car = props.physics.add_dynamic(None, Proxy.box((1.0, 1.0, 1.0)), mass=900.0,
                                        translation=(0.0, 0.6, 0.0))
        car.set_velocity((0.0, 0.0, 12.0))
        _run(props, 1.5)
        assert float(car.position[2]) < 6.5


class TestAPropThatIsNotABlock:
    """A boulder is a block because what a car needs from one is that it stops
    there. A stone lying in the grass is the other case: it is *ground* --
    something a wheel rides over and a walker steps onto -- and a block the size
    of it is a kerb across the hillside."""

    def _stone(self, at=(0.0, 0.0, 0.0), radius=0.45, height=0.5):
        return Prop(kind='stone', position=at, radius=radius, height=height,
                    shape='dome')

    def test_a_dome_stands_as_tall_as_it_was_measured(self) -> None:
        props = _stood([self._stone(at=(0.0, 10.0, 0.0), radius=0.5, height=0.5)])
        assert _body(props).proxy.kind == 'sphere'
        # A stone as wide as it is tall is a hemisphere: the sphere's middle
        # sits at the foot and its top stands the stone's height above it.
        assert float(_at(props)[1]) == pytest.approx(10.0, abs=0.01)

    def test_and_no_wider_than_the_stone_is(self) -> None:
        props = _stood([self._stone(radius=0.4, height=0.5)])
        assert float(_body(props).proxy.params['radius']) == pytest.approx(0.4, abs=0.01)
        # Sunk far enough that the top still stands where the stone's does.
        assert float(_at(props)[1]) == pytest.approx(0.1, abs=0.01)

    def test_a_dome_taller_than_it_is_wide_rests_on_the_ground(self) -> None:
        props = _stood([self._stone(radius=0.3, height=1.0)])
        # The sphere cannot reach the measured height without leaving the
        # ground, so it stands on the foot and its top is 2 * radius up.
        assert float(_at(props)[1]) == pytest.approx(0.3, abs=0.01)

    def test_a_prop_that_says_nothing_is_still_a_block(self) -> None:
        props = _stood([Prop(kind='rock', position=(0.0, 0.0, 0.0), radius=1.0, height=2.0)])
        assert _body(props).proxy.kind == 'box'

    def test_a_wheel_rides_over_one_rather_than_stopping_against_it(self) -> None:
        """The point of the whole thing: a stone in the road is a bump, and a
        block the same size is a wall."""
        props = _stood([self._stone(at=(0.0, 0.0, 8.0), radius=0.3, height=0.35)])
        _ground(props)
        wheel = props.physics.add_dynamic(None, Proxy.sphere(0.35), mass=40.0,
                                          translation=(0.0, 0.35, 0.0))
        wheel.set_velocity((0.0, 0.0, 14.0))
        # The ball reaches the stone at 7.8 m/s, rises over it and comes down
        # beyond it at about 1.9 m/s, past z = 9 by 1.6 s; against a block it
        # would stop at the block's face.
        _run(props, 2.5)
        assert float(wheel.position[2]) > 9.0

    def test_a_stone_is_something_to_stand_on(self) -> None:
        """Dropped onto one, a body comes to rest above the ground it lies on
        rather than on the ground beside it."""
        props = _stood([self._stone(radius=0.8, height=0.9)])
        _ground(props)
        body = props.physics.add_dynamic(None, Proxy.sphere(0.25), mass=80.0,
                                         translation=(0.0, 3.0, 0.0))
        _run(props, 2.5)
        assert float(body.position[1]) > 0.8


class TestSayingWhichShapeAPropIs:
    def test_a_prop_is_a_block_unless_it_says_otherwise(self) -> None:
        assert Prop(kind='rock', position=(0, 0, 0)).shape == 'box'

    def test_the_shape_survives_the_bake(self) -> None:
        one = Prop(kind='stone', position=(1, 2, 3), shape='dome')
        assert Prop.from_json(one.to_json()).shape == 'dome'

    def test_a_shape_nothing_can_stand_up_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Prop(kind='rock', position=(0, 0, 0), shape='teapot')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
