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


def test_identity_quat_yields_zero_angle_default_axis():
    # w ~ 1 -> sin(angle/2) ~ 0: no well-defined axis, so a safe default is used.
    rot = quat_to_vrml_rotation((0.0, 0.0, 0.0, 1.0))
    assert np.allclose(rot, (0.0, 1.0, 0.0, 0.0))


def _registered_body(translation=(0, 0, 0), rotation=(0, 1, 0, 0.0), motion=None):
    t = Transform(translation=translation, rotation=rotation)
    mgr = PhysicsManager(gravity=model.Gravity(gravity=0.0))
    body = PhysicsBody(t, motion if motion is not None else model.Motion(type=model.DYNAMIC))
    mgr.add(body)
    return mgr, body, t


def test_push_authored_pose_copies_transform_into_world():
    mgr, body, t = _registered_body()
    t.translation = (3.0, 4.0, 5.0)
    t.rotation = (0.0, 1.0, 0.0, 1.5)
    body.push_authored_pose()
    i = body.index
    assert np.allclose(mgr.world.position[i], (3.0, 4.0, 5.0))
    assert np.allclose(mgr.world.orientation[i], vrml_rotation_to_quat((0, 1, 0, 1.5)))


def test_push_authored_pose_noop_when_unregistered():
    body = PhysicsBody(Transform(), model.Motion())
    assert body.index is None
    body.push_authored_pose()                     # must not raise without a world


def test_sync_to_scene_writes_interpolated_pose():
    mgr, body, t = _registered_body()
    i = body.index
    w = mgr.world
    w.prev_position[i] = (0.0, 0.0, 0.0)
    w.position[i] = (10.0, 0.0, 0.0)
    w.prev_orientation[i] = vrml_rotation_to_quat((0, 1, 0, 0.0))
    w.orientation[i] = vrml_rotation_to_quat((0, 1, 0, 0.0))
    w.awake[i] = True
    body.sync_to_scene(alpha=0.5)
    assert t.translation[0] == pytest.approx(5.0)   # halfway between prev and cur


def test_sync_to_scene_skips_sleeping_dynamic_body():
    mgr, body, t = _registered_body()
    i = body.index
    w = mgr.world
    w.position[i] = (99.0, 0.0, 0.0)
    w.awake[i] = False
    w.motion_type[i] = 2                            # dynamic + asleep -> no writeback
    before = tuple(t.translation)
    body.sync_to_scene()
    assert tuple(t.translation) == before


def test_sync_to_scene_noop_when_unregistered():
    body = PhysicsBody(Transform(), model.Motion())
    body.sync_to_scene()                            # must not raise without a world


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
