"""Phase 0 scenegraph sync: physics drives Transform, no GL required."""
import numpy as np
import pytest

from OpenGLContext.scenegraph.transform import Transform
from omi_physics import model
from OpenGLContext.physics.manager import PhysicsManager
from OpenGLContext.scenegraph.physicsbody import PhysicsBody, quat_to_vrml_rotation, vrml_rotation_to_quat


def test_step_writes_translation_back_to_transform():
    t = Transform(translation=(0, 10, 0))
    mgr = PhysicsManager(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    mgr.add(PhysicsBody(t, model.Motion(type=model.DYNAMIC)))
    for _ in range(30):
        mgr.advance(1 / 60)
    assert t.translation[1] < 10.0                # it fell
    # transform tracks the world within one interpolated step
    assert mgr.world.position[0][1] == pytest.approx(t.translation[1], abs=0.1)


def test_kinematic_reads_authored_velocity():
    t = Transform(translation=(0, 0, 0))
    mgr = PhysicsManager(gravity=model.Gravity(gravity=9.81))
    mgr.add(PhysicsBody(t, model.Motion(type=model.KINEMATIC,
                                        linearVelocity=(1, 0, 0))))
    for _ in range(60):
        mgr.advance(1 / 60)
    assert mgr.world.position[0][0] == pytest.approx(1.0, rel=1e-6)
    assert mgr.world.position[0][1] == pytest.approx(0.0, abs=1e-12)   # gravity ignored
    assert t.translation[0] > 0.9                 # transform tracks the mover


def test_static_body_writes_nothing():
    t = Transform(translation=(5, 5, 5))
    mgr = PhysicsManager(gravity=model.Gravity(gravity=9.81))
    mgr.add(PhysicsBody(t, model.Motion(type=model.STATIC)))
    for _ in range(60):
        mgr.advance(1 / 60)
    assert np.allclose(t.translation, (5, 5, 5))


def test_sleeping_stops_writeback():
    t = Transform(translation=(0, 0, 0))
    mgr = PhysicsManager(gravity=model.Gravity(gravity=0.0))   # no force, at rest
    mgr.add(PhysicsBody(t, model.Motion(type=model.DYNAMIC)))
    for _ in range(120):
        mgr.advance(1 / 60)
    assert not mgr.world.awake[0]                 # went to sleep
    resting = t.translation.copy()
    for _ in range(60):
        mgr.advance(1 / 60)
    assert np.allclose(t.translation, resting)


def test_rotation_roundtrip():
    q = vrml_rotation_to_quat((0, 1, 0, 1.2))
    axis, angle = quat_to_vrml_rotation(q)[:3], quat_to_vrml_rotation(q)[3]
    assert np.allclose(axis, (0, 1, 0), atol=1e-9)
    assert angle == pytest.approx(1.2, abs=1e-9)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
