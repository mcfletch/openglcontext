"""Empty-world fast path for :class:`OpenGLContext.physics.manager.PhysicsManager`.

``sync`` must short-circuit when the world holds no bodies -- the numpy pose
interpolation would otherwise operate on empty arrays for nothing. This pins that
guard on a real, body-less world.
"""
from omi_physics import model
from OpenGLContext.physics.manager import PhysicsManager


def test_sync_on_a_body_less_world_is_a_noop():
    """advance/sync return without error and touch nothing when there are no bodies."""
    mgr = PhysicsManager(gravity=model.Gravity(gravity=9.81))
    assert mgr.world.body_count == 0
    mgr.sync()                                   # exercises the n == 0 early return
    alpha = mgr.advance(1 / 60)
    assert 0.0 <= float(alpha) <= 1.0            # advance still returns a valid alpha
    assert mgr.world.body_count == 0


if __name__ == '__main__':
    import sys
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
