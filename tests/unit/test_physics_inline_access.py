"""An inline Physics lets code that reads the world's arrays find its bodies and its clock.

A game that applies forces to the live world itself (a vehicle, a rule that
reads contacts) needs the slot a body has in the omi world (``physics_testing.inspect``), the queued
writes applied before it reads, and a way to drop the time left over from a
frame when it starts something afresh.
"""
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing import physics as physics_testing

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
STEP = 1.0 / 100.0


def crate(at=(0, 2, 0)):
    return surfaces.shape(surfaces.block((1, 1, 1)), LOOK, translation=at)


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=100.0, maxCatchUp=1.0))
    yield service
    service.close()


def test_index_of_is_the_slot_of_the_body_in_the_world(physics):
    first = physics.add_kinematic(crate())
    second = physics.add_kinematic(crate((5, 2, 0)))
    world = physics_testing.inspect(physics)
    assert world.bodies[physics_testing.slot_of(physics, second)] == second.uid
    assert world.bodies[physics_testing.slot_of(physics, first)] == first.uid
    assert physics_testing.slot_of(physics, first) != physics_testing.slot_of(physics, second)


def test_index_of_applies_the_add_that_is_still_queued(physics):
    body = physics.add_dynamic(crate((1, 2, 3)))
    assert world_position(physics, body) == pytest.approx((1, 2, 3))


def test_index_of_refuses_a_body_that_has_been_removed(physics):
    body = physics.add_kinematic(crate())
    physics.flush()
    body.remove()
    with pytest.raises(KeyError):
        physics_testing.slot_of(physics, body)


def test_index_of_is_for_inline_mode():
    threaded = Physics(PhysicsDefinition(mode='thread'))
    try:
        body = threaded.add_kinematic(crate())
        with pytest.raises(RuntimeError):
            physics_testing.slot_of(threaded, body)
    finally:
        threaded.close()


def test_flush_applies_the_writes_made_since_the_last_step(physics):
    body = physics.add_kinematic(crate())
    physics.flush()
    body.set_transform((4, 5, 6))
    body.set_velocity((1, 0, 0))
    physics.flush()
    index = physics_testing.slot_of(physics, body)
    assert tuple(physics_testing.inspect(physics).position[index]) == pytest.approx((4, 5, 6))
    assert tuple(physics_testing.inspect(physics).linear_velocity[index]) == pytest.approx((1, 0, 0))


def test_flush_does_not_step_the_world(physics):
    physics.add_dynamic(crate())
    before = physics_testing.inspect(physics).step_count
    physics.flush()
    assert physics_testing.inspect(physics).step_count == before


def test_time_left_over_from_a_frame_carries_to_the_next_step(physics):
    physics.step(STEP * 0.6)
    assert physics_testing.inspect(physics).step_count == 0
    physics.step(STEP * 0.6)
    assert physics_testing.inspect(physics).step_count == 1


def test_drop_remainder_forgets_the_time_left_over(physics):
    physics.step(STEP * 0.6)
    physics.drop_remainder()
    physics.step(STEP * 0.6)
    assert physics_testing.inspect(physics).step_count == 0


def test_drop_remainder_leaves_the_steps_already_run(physics):
    physics.step(STEP * 2.5)
    physics.drop_remainder()
    assert physics_testing.inspect(physics).step_count == 2


def world_position(physics, body):
    index = physics_testing.slot_of(physics, body)
    return tuple(physics_testing.inspect(physics).position[index])


def test_a_shape_proxy_body_is_found_the_same_way(physics):
    body = physics.add_static(crate(), proxy=Proxy.box((1, 1, 1)))
    assert physics_testing.inspect(physics).bodies[physics_testing.slot_of(physics, body)] == body.uid
