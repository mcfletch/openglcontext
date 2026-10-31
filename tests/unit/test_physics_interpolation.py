"""Frames drawn between ticks: a placed body is drawn where it was put, and thread mode interpolates.

A frame shorter than a tick draws moving bodies between the last two
ticks. A body placed by ``set_transform`` or ``restore_state`` is drawn at
its new place from the first frame that includes the place, never between
the old place and the new.
"""
import time

import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.transform import Transform

pytest.importorskip('pyjoltphysics')

TICK = 1.0 / 60.0


def moving_body(mode='inline'):
    physics = Physics(PhysicsDefinition(mode=mode, tickHz=60.0, maxCatchUp=2.0,
                                        gravity=(0.0, 0.0, 0.0)))
    node = Transform(translation=(0.0, 0.0, 0.0))
    body = physics.add_dynamic(node, proxy=Proxy.sphere(0.5), mass=1.0)
    body.set_velocity((1.0, 0.0, 0.0))
    return physics, node, body


def test_a_placed_body_is_drawn_at_its_new_place_on_the_first_frame():
    physics, node, body = moving_body()
    try:
        for _ in range(10):
            physics.frame(1.5 * TICK)       # frames of a tick and a half: alpha is a half
        body.set_transform(translation=(100.0, 0.0, 0.0))
        for frame in range(1, 4):
            physics.frame(1.5 * TICK)
            # At 1 m/s it goes on from the new place by at most the ticks run since.
            assert 100.0 <= node.translation[0] <= 100.0 + (1.5 * frame + 1.0) * TICK
            assert body.position[0] == pytest.approx(node.translation[0])
    finally:
        physics.close()


def test_a_restored_state_is_drawn_without_a_blend_from_where_the_bodies_were():
    physics, node, body = moving_body()
    try:
        physics.frame(TICK)
        saved = physics.save_state()
        for _ in range(60):
            physics.frame(1.5 * TICK)
        assert node.translation[0] > 1.0
        physics.restore_state(saved)
        physics.frame(1.5 * TICK)
        assert node.translation[0] < 0.2
    finally:
        physics.close()


@pytest.mark.serial  # frames paced by the wall clock against a world thread paced by it too
def test_thread_mode_draws_each_frame_between_the_last_two_ticks():
    physics, node, body = moving_body('thread')
    try:
        physics.frame(1.0 / 240.0)
        seen = []
        last = time.perf_counter()
        for _ in range(240):
            target = last + 1.0 / 240.0
            while time.perf_counter() < target:
                pass
            now = time.perf_counter()
            physics.frame(now - last)
            last = now
            seen.append(float(node.translation[0]))
        repeated = sum(1 for first, second in zip(seen, seen[1:]) if first == second)
        assert repeated < 0.05 * len(seen)
        steps = [second - first for first, second in zip(seen, seen[1:])]
        assert min(steps) >= 0.0
    finally:
        physics.close()
