"""What a frame of a settled Jolt world does: its ticks are counted, its poses are not copied.

A lockstep world whose bodies are all asleep and that nothing acts on runs its
ticks as pyjoltphysics' quiet ticks, and the engine publishes the snapshot
before it again with the new tick. Woken, the world plays out as one whose
every tick was stepped.
"""
import numpy as np
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.basenodes import Transform


FRAME = 1.0 / 60.0


def settled(count: int = 12) -> tuple[Physics, list]:
    """An inline service whose ``count`` boxes have come to rest on a floor."""
    physics = Physics(PhysicsDefinition(mode='inline', tickHz=120.0))
    physics.add_static(None, Proxy.box((40, 1, 40)), translation=(0, -0.5, 0))
    bodies = [physics.add_dynamic(Transform(translation=((i % 4) * 1.5, 0.4 + 0.6 * (i // 4), 0.0)),
                                  Proxy.box((0.5, 0.5, 0.5)), mass=1.0)
              for i in range(count)]
    for _ in range(3000):
        physics.frame(FRAME)
        if all(body.asleep for body in bodies):
            # The frames that make the world quiet: one reports the contacts' removal, two report nothing.
            for _ in range(3):
                physics.frame(FRAME)
            return physics, bodies
    raise AssertionError('the boxes did not come to rest')


def test_a_settled_world_counts_its_ticks_and_publishes_its_poses_again():
    physics, _bodies = settled()
    try:
        world = physics._engine.world
        before = physics._snapshot
        start = physics.time
        world.reset_stats()
        for _ in range(30):
            physics.frame(FRAME)
        after = physics._snapshot
        assert world.stats()['quiet_ticks'] == 60
        assert physics.time == pytest.approx(start + 0.5)
        assert after.version > before.version
        assert after.position is before.position
        assert len(after.changed) == 0
    finally:
        physics.close()


def test_a_body_moved_by_hand_in_a_settled_world_is_published_where_it_was_put():
    physics, bodies = settled()
    try:
        bodies[0].set_transform((10.0, 0.25, 3.0))
        physics.frame(FRAME)
        assert np.allclose(bodies[0].node.translation, (10.0, 0.25, 3.0), atol=1e-3)
        assert np.allclose(bodies[0].position, (10.0, 0.25, 3.0), atol=1e-3)
    finally:
        physics.close()


def test_a_woken_settled_world_plays_out_as_one_stepped_through_every_tick():
    results = []
    for stepped in (True, False):
        physics, bodies = settled()
        try:
            hook = physics.on_step(lambda view: None) if stepped else None
            physics._engine.world.reset_stats()
            for _ in range(60):
                physics.frame(FRAME)
            quiet = physics._engine.world.stats()['quiet_ticks']
            assert (quiet == 0) if stepped else (quiet == 120)
            if hook is not None:
                hook.cancel()
            bodies[5].apply_impulse((0.5, 3.0, 0.0))
            for _ in range(120):
                physics.frame(FRAME)
            results.append(np.array([body.position for body in bodies]))
        finally:
            physics.close()
    assert np.array_equal(results[0], results[1])
    assert not np.array_equal(results[0][5], [4.5, 0.25, 0.0])
