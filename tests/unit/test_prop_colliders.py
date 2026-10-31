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
from omi_physics.world import PhysicsWorld
from omi_physics import model

from OpenGLContext.physics.body import Body
from OpenGLContext.physics.props import PropColliders, PropSource
from OpenGLContext.scenegraph.props import Prop
from tests.unit._streamed import Streamed

pytestmark = pytest.mark.engines('omi', reason='reads the omi world the colliders are made in')


def _scattered(count=40, spacing=25.0):
    return [Prop(kind='rock', position=(index * spacing, 0.0, 0.0),
                 radius=1.0, height=1.4)
            for index in range(count)]


def _world():
    return PhysicsWorld()


def _shape_of(world, body):
    """The shape a body was stood up with."""
    return world.shapes[world.collider_shape[body]]


def _held(world):
    """How many bodies the world is actually carrying.

    A removed body leaves its slot behind for the next one to take, so the
    number of *rows* is the high-water mark rather than what is live.
    """
    return int(world.live_body_count)


class TestASource:
    """:class:`PropSource` makes the bodies through a physics service."""

    def test_each_prop_within_reach_is_a_body_of_the_service(self) -> None:
        props = Streamed(PropSource(_scattered(), reach=60.0))
        props.update((0.0, 0.0, 0.0))
        hit = props.physics.raycast((0.0, 20.0, 0.0), (0.0, -1.0, 0.0), 40.0)
        assert isinstance(hit.body, Body)
        assert hit.point[1] == pytest.approx(1.4, abs=0.01)
        assert props.world.live_body_count == len(props.standing)

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
        props = Streamed(PropSource(_scattered(), reach=60.0))
        props.update((0.0, 0.0, 0.0))
        props.clear()
        assert props.standing == []
        assert props.world.live_body_count == 0
        assert props.source.update((0.0, 0.0, 0.0)).add

    def test_a_body_stands_where_the_world_form_stands_it(self) -> None:
        """The source and :class:`PropColliders` agree about every prop."""
        stones = [Prop(kind='stone', position=(3.0, 1.0, 2.0), radius=0.3, height=1.0,
                       shape='dome', yaw=0.7),
                  Prop(kind='rock', position=(-4.0, 2.0, 1.0), radius=1.2, height=2.0, yaw=1.1)]
        plain = _world()
        PropColliders(plain, stones).update((0.0, 0.0, 0.0))
        served = Streamed(PropSource(stones))
        served.update((0.0, 0.0, 0.0))
        world = served.world
        for row in range(2):
            assert np.allclose(world.position[row], plain.position[row])
            assert np.allclose(world.orientation[row], plain.orientation[row])
            assert _shape_of(world, row).type == _shape_of(plain, row).type


class TestWhatIsHeld:
    def test_nothing_before_the_first_update(self) -> None:
        world = _world()
        props = PropColliders(world, _scattered())
        assert _held(world) == 0 and props.standing == []

    def test_the_ones_within_reach_are_stood_up(self) -> None:
        world = _world()
        props = PropColliders(world, _scattered(), reach=60.0)
        props.update((0.0, 0.0, 0.0))
        assert 2 <= _held(world) <= 6
        assert _held(world) == len(props.standing)

    def test_the_far_ones_are_not(self) -> None:
        world = _world()
        props = PropColliders(world, _scattered(), reach=60.0)
        props.update((0.0, 0.0, 0.0))
        assert _held(world) < 40

    def test_walking_along_brings_the_next_ones(self) -> None:
        world = _world()
        props = PropColliders(world, _scattered(), reach=60.0)
        props.update((0.0, 0.0, 0.0))
        props.update((500.0, 0.0, 0.0))
        assert props.standing
        assert all(abs(one.position[0] - 500.0) <= 60.0
                   for one in props.standing)

    def test_and_takes_away_the_ones_behind(self) -> None:
        """A lap holds what a lap can reach, not everything it has passed."""
        world = _world()
        props = PropColliders(world, _scattered(), reach=60.0)
        for along in range(0, 1000, 40):
            props.update((float(along), 0.0, 0.0))
        assert _held(world) <= 6
        assert not any(one.position[0] < 400.0 for one in props.standing)

    def test_standing_still_changes_nothing(self) -> None:
        world = _world()
        props = PropColliders(world, _scattered(), reach=60.0)
        props.update((0.0, 0.0, 0.0))
        before = list(props.standing)
        props.update((1.0, 0.0, 1.0))
        assert list(props.standing) == before

    def test_a_world_with_no_props_is_not_an_error(self) -> None:
        world = _world()
        PropColliders(world, []).update((0.0, 0.0, 0.0))
        assert _held(world) == 0


class TestWhatABodyIs:
    def test_it_is_where_the_prop_is(self) -> None:
        world = _world()
        props = PropColliders(world, [Prop(kind='rock',
                                           position=(4.0, 7.0, -2.0),
                                           radius=1.0, height=2.0)])
        props.update((0.0, 0.0, 0.0))
        at = world.position[0]
        assert float(at[0]) == pytest.approx(4.0, abs=0.01)
        assert float(at[2]) == pytest.approx(-2.0, abs=0.01)

    def test_its_middle_is_half_its_height_up(self) -> None:
        """A prop's position is its foot; a box's is its centre."""
        world = _world()
        props = PropColliders(world, [Prop(kind='rock',
                                           position=(0.0, 10.0, 0.0),
                                           radius=1.0, height=2.0)])
        props.update((0.0, 0.0, 0.0))
        assert float(world.position[0][1]) == pytest.approx(11.0, abs=0.01)

    def test_it_does_not_move(self) -> None:
        world = _world()
        PropColliders(world, [Prop(kind='rock', position=(0.0, 0.0, 0.0))]
                      ).update((0.0, 0.0, 0.0))
        before = world.position[0].copy()
        for _ in range(30):
            world.step(1.0 / 60.0)
        assert np.allclose(world.position[0], before)

    def test_a_car_stops_against_one(self) -> None:
        """The point of the whole thing."""
        world = _world()
        ground = world.add_shape(model.Shape.box((400.0, 2.0, 400.0)))
        world.add_body(model.Motion(type=model.STATIC),
                       collider=model.Collider(shape=ground),
                       position=(0.0, -1.0, 0.0))
        props = PropColliders(world, [Prop(kind='rock', position=(0.0, 0.0, 8.0),
                                           radius=2.0, height=3.0)])
        props.update((0.0, 0.0, 0.0))
        box = world.add_shape(model.Shape.box((1.0, 1.0, 1.0)))
        car = world.add_body(model.Motion(type=model.DYNAMIC, mass=900.0),
                             collider=model.Collider(shape=box),
                             position=(0.0, 0.6, 0.0))
        world.linear_velocity[car] = (0.0, 0.0, 12.0)
        for _ in range(180):
            world.step(1.0 / 120.0)
        assert float(world.position[car][2]) < 6.5


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestAPropThatIsNotABlock:
    """A boulder is a block because what a car needs from one is that it stops
    there. A stone lying in the grass is the other case: it is *ground* --
    something a wheel rides over and a walker steps onto -- and a block the size
    of it is a kerb across the hillside."""

    def _stone(self, at=(0.0, 0.0, 0.0), radius=0.45, height=0.5):
        return Prop(kind='stone', position=at, radius=radius, height=height,
                    shape='dome')

    def test_a_dome_stands_as_tall_as_it_was_measured(self) -> None:
        world = _world()
        PropColliders(world, [self._stone(at=(0.0, 10.0, 0.0), radius=0.5,
                                          height=0.5)]).update((0, 0, 0))
        assert _shape_of(world, 0).type == 'sphere'
        # A stone as wide as it is tall is a hemisphere: the sphere's middle
        # sits at the foot and its top stands the stone's height above it.
        assert float(world.position[0][1]) == pytest.approx(10.0, abs=0.01)

    def test_and_no_wider_than_the_stone_is(self) -> None:
        world = _world()
        PropColliders(world, [self._stone(radius=0.4, height=0.5)]
                      ).update((0, 0, 0))
        assert float(_shape_of(world, 0).radius) == pytest.approx(0.4, abs=0.01)
        # Sunk far enough that the top still stands where the stone's does.
        assert float(world.position[0][1]) == pytest.approx(0.1, abs=0.01)

    def test_a_dome_taller_than_it_is_wide_rests_on_the_ground(self) -> None:
        world = _world()
        PropColliders(world, [self._stone(radius=0.3, height=1.0)]
                      ).update((0, 0, 0))
        # The sphere cannot reach the measured height without leaving the
        # ground, so it stands on the foot and its top is 2 * radius up.
        assert float(world.position[0][1]) == pytest.approx(0.3, abs=0.01)

    def test_a_prop_that_says_nothing_is_still_a_block(self) -> None:
        world = _world()
        PropColliders(world, [Prop(kind='rock', position=(0.0, 0.0, 0.0),
                                   radius=1.0, height=2.0)]).update((0, 0, 0))
        assert _shape_of(world, 0).type == 'box'

    def test_a_wheel_rides_over_one_rather_than_stopping_against_it(self) -> None:
        """The point of the whole thing: a stone in the road is a bump, and a
        block the same size is a wall."""
        world = _world()
        ground = world.add_shape(model.Shape.box((400.0, 2.0, 400.0)))
        world.add_body(model.Motion(type=model.STATIC),
                       collider=model.Collider(shape=ground),
                       position=(0.0, -1.0, 0.0))
        props = PropColliders(world, [self._stone(at=(0.0, 0.0, 8.0),
                                                  radius=0.3, height=0.35)])
        props.update((0.0, 0.0, 0.0))
        ball = world.add_shape(model.Shape.sphere(0.35))
        wheel = world.add_body(model.Motion(type=model.DYNAMIC, mass=40.0),
                               collider=model.Collider(shape=ball),
                               position=(0.0, 0.35, 0.0))
        world.linear_velocity[wheel] = (0.0, 0.0, 14.0)
        for _ in range(180):
            world.step(1.0 / 120.0)
        assert float(world.position[wheel][2]) > 9.0

    def test_a_stone_is_something_to_stand_on(self) -> None:
        """Dropped onto one, a body comes to rest above the ground it lies on
        rather than on the ground beside it."""
        world = _world()
        ground = world.add_shape(model.Shape.box((400.0, 2.0, 400.0)))
        world.add_body(model.Motion(type=model.STATIC),
                       collider=model.Collider(shape=ground),
                       position=(0.0, -1.0, 0.0))
        props = PropColliders(world, [self._stone(radius=0.8, height=0.9)])
        props.update((0.0, 0.0, 0.0))
        ball = world.add_shape(model.Shape.sphere(0.25))
        body = world.add_body(model.Motion(type=model.DYNAMIC, mass=80.0),
                              collider=model.Collider(shape=ball),
                              position=(0.0, 3.0, 0.0))
        for _ in range(300):
            world.step(1.0 / 120.0)
        assert float(world.position[body][1]) > 0.8


class TestSayingWhichShapeAPropIs:
    def test_a_prop_is_a_block_unless_it_says_otherwise(self) -> None:
        assert Prop(kind='rock', position=(0, 0, 0)).shape == 'box'

    def test_the_shape_survives_the_bake(self) -> None:
        one = Prop(kind='stone', position=(1, 2, 3), shape='dome')
        assert Prop.from_json(one.to_json()).shape == 'dome'

    def test_a_shape_nothing_can_stand_up_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Prop(kind='rock', position=(0, 0, 0), shape='teapot')
