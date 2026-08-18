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

from OpenGLContext.physics.props import PropColliders
from OpenGLContext.scenegraph.props import Prop


def _scattered(count=40, spacing=25.0):
    return [Prop(kind='rock', position=(index * spacing, 0.0, 0.0),
                 radius=1.0, height=1.4)
            for index in range(count)]


def _world():
    return PhysicsWorld()


def _held(world):
    """How many bodies the world is actually carrying.

    A removed body leaves its slot behind for the next one to take, so the
    number of *rows* is the high-water mark rather than what is live.
    """
    return int(world.live_body_count)


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
        from omi_physics import model
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
