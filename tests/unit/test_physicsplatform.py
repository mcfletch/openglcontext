"""Walk-with-gravity view platform (:mod:`OpenGLContext.move.physicsplatform`).

``PhysicsViewPlatform`` owns a :class:`omi_physics.character.CharacterController`
capsule and turns navigation input into camera pose. These tests drive it against a
real world with a flat ground trimesh: eye-anchored binding, pitch clamping, jump,
crouch, and the ``blocked`` (airborne-and-stuck) predicate -- asserting real state
changes, not just absence of errors.
"""
import numpy as np
import pytest

from omi_physics import model
from omi_physics.world import PhysicsWorld
from omi_physics.character import CharacterCapabilities
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform


def _ground_world():
    """A world with a large static floor at y=0 so the character can stand."""
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    pts = np.array([(-50, 0, -50), (50, 0, -50), (50, 0, 50), (-50, 0, 50)], dtype='d')
    tris = np.array([(0, 1, 2), (0, 2, 3)], dtype='i')
    shape = world.add_shape(model.Shape.trimesh(pts, tris))
    world.add_body(model.Motion(type=model.STATIC),
                   collider=model.Collider(shape=shape), position=(0, 0, 0))
    return world


def _platform(**kw):
    return PhysicsViewPlatform(_ground_world(), CharacterCapabilities(), **kw)


def test_bind_eye_places_the_camera_eye_at_the_requested_height():
    """bind_eye offsets by (half-height - eyeHeight) so the eye lands where asked."""
    plat = _platform()
    plat.bind_eye((0, 1.7, 0))
    eye = plat.camera_position()
    assert eye[1] == pytest.approx(1.7, abs=0.3)     # near the requested eye height
    assert (eye[0], eye[2]) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_look_clamps_pitch_to_its_limits():
    """look() accumulates pitch but never past +/-1.4 radians."""
    plat = _platform()
    plat.look(10.0)
    assert plat.pitch == pytest.approx(1.4)
    plat.look(-100.0)
    assert plat.pitch == pytest.approx(-1.4)


def test_jump_fires_only_when_grounded():
    """A grounded capsule jumps; an airborne one does not."""
    plat = _platform()
    plat.bind((0, 1.0, 0))
    plat.update(1 / 60)                              # settle onto the floor
    plat.character.grounded = True
    assert plat.jump() is True
    plat.character.grounded = False
    assert plat.jump() is False


def test_set_crouch_toggles_the_character_crouch_state():
    """set_crouch drives the underlying controller's crouch flag."""
    plat = _platform()
    plat.bind((0, 1.0, 0))
    plat.set_crouch(True)
    assert plat.character.crouching is True
    plat.set_crouch(False)
    assert plat.character.crouching is False


def test_blocked_is_true_only_when_airborne_and_stuck():
    """blocked reports an ungrounded capsule that cannot move (stuck)."""
    plat = _platform()
    plat.character.grounded = False
    plat.character.stuck = True
    assert plat.blocked is True
    plat.character.grounded = True                   # grounded -> not blocked
    assert plat.blocked is False
    plat.character.grounded = False
    plat.character.stuck = False                     # free -> not blocked
    assert plat.blocked is False


def test_world_dir_basis_matches_yaw():
    """At yaw 0 forward is world -Z and strafe is world +X."""
    plat = _platform()
    plat.yaw = 0.0
    assert np.allclose(plat._world_dir(1.0, 0.0), (0, 0, -1))
    assert np.allclose(plat._world_dir(0.0, 1.0), (1, 0, 0))


def test_turn_accumulates_yaw():
    plat = _platform()
    plat.turn(0.5)
    plat.turn(0.25)
    assert plat.yaw == pytest.approx(0.75)


def test_walking_forward_moves_the_camera_along_facing():
    """set_move + update walks the capsule along its forward (world -Z at yaw 0)."""
    plat = _platform()
    plat.bind((0, 1.0, 0))
    for _ in range(20):
        plat.update(1 / 60)                          # settle onto the floor
    plat.set_move(forward=1.0, mode='run')
    for _ in range(60):
        plat.update(1 / 60)
    pos = plat.camera_position()
    assert pos[2] < -1.0                             # walked toward -Z
    assert abs(pos[0]) < 1e-6


def test_fly_move_lifts_the_camera_when_flying():
    """set_fly enables noclip flight; set_fly_move(up) raises the eye."""
    plat = _platform()
    plat.bind((0, 1.0, 0))
    plat.update(1 / 60)
    y0 = plat.camera_position()[1]
    plat.set_fly(True)
    plat.set_fly_move(up=1.0)
    for _ in range(30):
        plat.update(1 / 60)
    assert plat.camera_position()[1] > y0 + 0.5


def test_apply_writes_pose_onto_the_context_platform():
    """apply pushes the camera position and orientation onto a context's platform."""
    class _P:
        pos = None
        orient = None

        def setPosition(self, p):
            self.pos = p

        def setOrientation(self, o):
            self.orient = o

    class _Ctx:
        platform = _P()

    plat = _platform()
    plat.bind((0, 1.0, 0))
    plat.update(1 / 60)
    plat.yaw = 0.3
    plat.pitch = -0.2
    ctx = _Ctx()
    plat.apply(ctx)
    assert ctx.platform.pos == plat.camera_position()
    assert np.allclose(ctx.platform.orient.internal,
                       plat.camera_orientation().internal)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
