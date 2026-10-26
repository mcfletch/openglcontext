"""Collision filters and contact filters on the physics service, with no raw world."""
import numpy as np
import pytest

from OpenGLContext.physics import CollisionFilter
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=2.0))
    service.gravity = (0, 0, 0)
    yield service
    service.close()


def run_for(physics, seconds, frame=1.0 / 60.0):
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


def ball(physics, at, velocity=(0, 0, 0), **options):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.25), translation=at, mass=1.0,
                               **options)
    body.set_velocity(velocity)
    return body


def wall(physics, **options):
    return physics.add_static(None, proxy=Proxy.box((0.2, 4.0, 4.0)), translation=(0, 0, 0),
                              **options)


BALLS = CollisionFilter(collisionSystems=('ball',))
SHARDS = CollisionFilter(collisionSystems=('shard',), notCollideWithSystems=('ball',))


def test_bodies_whose_filters_exclude_each_other_pass_through(physics):
    first = ball(physics, (-2, 0, 0), (4, 0, 0), collision_filter=BALLS)
    still = ball(physics, (0, 0, 0), collision_filter=SHARDS)
    run_for(physics, 1.0)
    assert float(first.position[0]) > 0.8
    assert np.allclose(still.position, (0, 0, 0), atol=1e-6)


def test_bodies_whose_filters_meet_collide(physics):
    ball(physics, (-2, 0, 0), (4, 0, 0), collision_filter=BALLS)
    struck = ball(physics, (0, 0, 0), collision_filter=CollisionFilter(collisionSystems=('ball',)))
    run_for(physics, 1.0)
    assert float(struck.position[0]) > 0.5


def test_one_filter_given_twice_is_one_filter_in_the_world(physics):
    ball(physics, (-2, 0, 0), collision_filter=BALLS)
    ball(physics, (2, 0, 0), collision_filter=CollisionFilter(collisionSystems=('ball',)))
    ball(physics, (4, 0, 0), collision_filter=SHARDS)
    physics.flush()
    assert len(physics.worker.runtime.world.filters) == 2


def test_an_index_names_a_filter_of_the_world_as_it_is(physics):
    physics.flush()
    physics.worker.runtime.world.add_filter(CollisionFilter(collisionSystems=('ball',)))
    body = ball(physics, (0, 0, 0), collision_filter=0)
    physics.flush()
    runtime = physics.worker.runtime
    assert int(runtime.world.collider_filter[runtime.entry(body.uid).index]) == 0


def test_a_contact_filter_answering_false_lets_a_ball_through_a_wall(physics):
    seen = []

    def through(approach):
        seen.append(approach)
        return False

    barrier = wall(physics)
    barrier.addEventHandler('hit', function=lambda hit: None)
    physics.set_contact_filter(through)
    moving = ball(physics, (-2, 0, 0), (5, 0, 0))
    run_for(physics, 1.0)
    assert float(moving.position[0]) > 1.5
    assert seen
    pair = {seen[0].first, seen[0].second}
    assert pair == {barrier, moving}
    assert seen[0].impulse == pytest.approx(5.0, rel=0.2)
    assert seen[0].approach == pytest.approx(5.0, rel=0.2)


def test_a_contact_filter_answering_true_solves_the_pair(physics):
    barrier = wall(physics)
    barrier.addEventHandler('hit', function=lambda hit: None)
    physics.set_contact_filter(lambda approach: True)
    moving = ball(physics, (-2, 0, 0), (5, 0, 0))
    run_for(physics, 1.0)
    assert float(moving.position[0]) < 0.0


def test_removing_the_contact_filter_solves_every_pair_again(physics):
    barrier = wall(physics)
    barrier.addEventHandler('hit', function=lambda hit: None)
    physics.set_contact_filter(lambda approach: False)
    physics.set_contact_filter(None)
    moving = ball(physics, (-2, 0, 0), (5, 0, 0))
    run_for(physics, 1.0)
    assert float(moving.position[0]) < 0.0


def test_a_contact_filter_that_raises_solves_the_pair_and_logs(physics, caplog):
    barrier = wall(physics)
    barrier.addEventHandler('hit', function=lambda hit: None)

    def broken(approach):
        raise RuntimeError('filter failed')

    physics.set_contact_filter(broken)
    moving = ball(physics, (-2, 0, 0), (5, 0, 0))
    run_for(physics, 1.0)
    assert float(moving.position[0]) < 0.0
    assert 'filter failed' in caplog.text


def test_a_contact_filter_works_on_the_physics_thread():
    import time

    physics = Physics(PhysicsDefinition(mode='thread', tickHz=120.0))
    try:
        physics.gravity = (0, 0, 0)
        barrier = wall(physics)
        barrier.addEventHandler('hit', function=lambda hit: None)
        physics.set_contact_filter(lambda approach: False)
        moving = ball(physics, (-2, 0, 0), (5, 0, 0))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and float(moving.position[0]) < 1.5:
            physics.frame(1.0 / 60.0)
            time.sleep(0.01)
        assert float(moving.position[0]) > 1.5
        assert np.isfinite(moving.position).all()
    finally:
        physics.close()
