"""Walking a height field with the declared movement modes.

:class:`~OpenGLContext.move.terrainwalk.TerrainWalkMixin` is the terrain form of
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`: the same avatar, the
same modes and the same keys, with the ground, the trunks and the rocks bodies in
the context's physics world and the avatar a character the service steps in the
frame.

These drive the whole path with no GL and no window -- a real
:class:`~OpenGLContext.events.inputstate.InputState`, a real
:class:`~OpenGLContext.move.navigation.NavigationManager`, real modes and a real
character controller -- so what is checked is where the walker actually ends up.
"""
import math

import numpy as np
import pytest

from OpenGLContext.move import modes as movemodes
from OpenGLContext.scenegraph.terrain import HeightField

from ._terrain_host import (
    FRAME, Clock, eye, flat_field, press, ramp_field, run, walking,
)


@pytest.fixture
def clock():
    made = Clock()
    yield made
    made.restore()


# -- the modes the terrain declares -------------------------------------------

class TestDeclaredModes:
    def test_walking_terrain_is_first_person(self, clock):
        """Mouse-look is the mode a landscape starts in, as it is in twig-bb."""
        host = walking(clock)
        declared = host.contextDefinition.navigation.movingModes()
        assert isinstance(declared[0], movemodes.FPSMode)
        assert declared[0].capturePointer

    def test_walking_and_flying_are_offered_as_well(self, clock):
        host = walking(clock)
        names = [str(mode.name) for mode in host.contextDefinition.navigation.movingModes()]
        assert names == ['fps', 'walk', 'fly']

    def test_a_host_that_declared_its_own_modes_keeps_them(self, clock):
        """The speeds a game chose are not overwritten by the defaults."""
        host = clock.host()
        host.contextDefinition.navigation.setMovingModes([
            movemodes.WalkMode(name='walk', walkSpeed=11.0)])
        host.init_walk(flat_field())
        host.setupPhysics(enable=True)
        declared = host.contextDefinition.navigation.movingModes()
        assert len(declared) == 1
        assert declared[0].walkSpeed == pytest.approx(11.0)

    def test_the_avatar_is_person_sized_whatever_the_terrain_spans(self, clock):
        """A height field is in world units, so nothing is scaled to its extent."""
        host = walking(clock, field=flat_field(extent=4096.0))
        assert host.physicsAvatarScale((-2048, 0, -2048), (2048, 450, 2048)) \
            == pytest.approx(1.0)
        assert host.physicsPlatform.character.caps.eyeHeight \
            == pytest.approx(host.eye_height)

    def test_the_avatar_steps_what_the_mix_in_says_and_stands_on_what_it_says(self, clock):
        host = walking(clock)
        caps = host.physicsPlatform.character.caps
        assert caps.stepHeight == pytest.approx(host.step_height)
        assert caps.maxSlope == pytest.approx(host.max_slope)
        assert caps.radius == pytest.approx(host.player_radius)


# -- the avatar is a character in the context's world --------------------------

class TestTheAvatarInTheWorld:
    def test_the_avatar_is_a_character_of_the_contexts_physics(self, clock):
        host = walking(clock)
        assert host.physics.characters == (host.physicsPlatform.managed,)

    def test_the_ground_and_the_trunks_are_bodies_of_that_world(self, clock):
        trunk = np.array([[0.0, 0.0, -6.0]], 'f')
        host = walking(clock, colliders=trunk, radii=np.array([0.5], 'f'))
        assert host.physics.raycast((10.0, 50.0, 10.0), (0, -1, 0)).body is host._tw_landscape.body  # noqa: SLF001 the landscape the mix-in keeps, which it does not expose
        assert host.physics.raycast((0.0, 5.5, -3.0), (0, 0, -1)).point[2] == pytest.approx(-5.5, abs=0.02)

    def test_a_context_whose_physics_is_switched_off_walks_all_the_same(self, clock):
        """Walking is the physics service, so binding a landscape switches it on."""
        host = clock.host(enabled=False)
        host.init_walk(flat_field(height=5.0))
        host.setupPhysics(enable=True)
        press(host, 'w')
        run(host, clock, 1.0)
        assert host.physics.definition.enabled
        assert eye(host)[1] == pytest.approx(5.0 + host.eye_height, abs=2e-3)
        assert eye(host)[2] < -1.0

    def test_a_ground_that_is_slow_to_sample_is_read_ahead_of_the_walker(self, clock):
        from OpenGLContext.scenegraph.rockground import RockyGround
        from OpenGLContext.scenegraph.terrain.relief import RockRelief

        rock = RockRelief(where=lambda x, z: np.ones(np.shape(x)), height=0.5)
        host = walking(clock, field=RockyGround(flat_field(height=5.0), rock, spacing=0.5))
        run(host, clock, 0.2)
        surface = host._tw_landscape.surface  # noqa: SLF001 the landscape the mix-in keeps, which it does not expose
        assert surface.wait(30.0)
        assert surface.tile_count >= 9

    def test_the_scenes_own_shapes_are_not_made_into_bodies(self, clock):
        host = walking(clock)
        assert host.physics.definition.colliders == 'explicit'

    def test_a_body_dropped_on_the_ground_rests_on_it(self, clock):
        from OpenGLContext.scenegraph import surfaces
        from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

        host = walking(clock, field=flat_field(height=5.0))
        ball = surfaces.shape(surfaces.sphere(0.3), PhysicalMaterial(), translation=(8.0, 9.0, 3.0))
        host.physics.add_dynamic(ball, proxy='sphere', restitution=0.0, friction=0.9)
        run(host, clock, 3.0)
        assert ball.translation[1] == pytest.approx(5.3, abs=0.03)

    def test_a_body_rolling_down_a_slope_strikes_a_trunk(self, clock):
        from OpenGLContext.scenegraph import surfaces
        from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

        field = ramp_field()
        host = walking(clock, field=field, colliders=np.array([[-8.0, 0.0, 0.0]], 'f'),
                       radii=np.array([0.5], 'f'), position=(40.0, 0.0, 40.0))
        start = (-4.0, field.height_at(-4.0, 0.0) + 0.3, 0.0)
        ball = surfaces.shape(surfaces.sphere(0.3), PhysicalMaterial(), translation=start)
        host.physics.add_dynamic(ball, proxy='sphere', restitution=0.0, friction=0.2)
        run(host, clock, 8.0)
        assert ball.translation[0] == pytest.approx(-8.0 + 0.5 + 0.3, abs=0.1)


# -- where the walker ends up -------------------------------------------------

class TestWalking:
    def test_the_walker_stands_at_eye_height_on_the_ground(self, clock):
        host = walking(clock, field=flat_field(height=5.0))
        run(host, clock, 0.2)
        assert eye(host)[1] == pytest.approx(5.0 + host.eye_height, abs=2e-3)

    def test_holding_forward_walks(self, clock):
        host = walking(clock)
        press(host, 'w')
        before = eye(host)
        run(host, clock, 1.0)
        after = eye(host)
        assert math.dist(before[::2], after[::2]) > 1.0

    def test_letting_go_stops(self, clock):
        host = walking(clock)
        press(host, 'w')
        run(host, clock, 0.5)
        press(host, 'w', state=0)
        run(host, clock, 0.2)
        stopped = eye(host)
        run(host, clock, 0.5)
        assert eye(host)[::2] == pytest.approx(stopped[::2], abs=1e-3)

    def test_the_eye_follows_the_slope(self, clock):
        """Walking uphill raises the camera by the ground it gained."""
        host = walking(clock, field=ramp_field())
        press(host, 'w')
        run(host, clock, 1.0)
        x, y, z = eye(host)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,  # noqa: SLF001 the height field the walk mixin holds, which it does not expose
                                  abs=0.02)

    def test_retuning_the_mode_retunes_the_walk(self, clock):
        """What the settings screen edits is what the avatar moves at.

        The screen writes the field on the live mode node, so the only thing
        that makes the number real is the mode carrying it down to the body
        every frame.
        """
        def walked(speed):
            host = walking(clock, position=(0.0, 0.0, 50.0))
            host.contextDefinition.navigation.movingModes()[0].walkSpeed = speed
            press(host, 'w')
            run(host, clock, 1.0)
            press(host, 'w', state=0)
            return math.dist((0.0, 50.0), (eye(host)[0], eye(host)[2]))
        assert walked(6.0) == pytest.approx(2 * walked(3.0), rel=0.05)

    def test_the_mouse_turns_the_view(self, clock):
        host = walking(clock)
        host.getInputState().mouse_moved(120.0, 0.0)
        run(host, clock, FRAME)
        assert host.physicsPlatform.yaw != pytest.approx(0.0)

    def test_the_frame_steps_the_walker_and_a_standing_one_asks_for_none(self, clock):
        host = walking(clock)
        run(host, clock, 0.5)
        host.redraws.clear()
        run(host, clock, 0.5)
        assert host.redraws == []
        press(host, 'w')
        run(host, clock, 0.5)
        assert host.redraws
        assert eye(host)[2] < -0.5


class TestObstacles:
    def test_a_trunk_stops_the_walker(self, clock):
        """The walker is pushed out of a cylinder rather than through it."""
        trunk = np.array([[0.0, 0.0, -6.0]], 'f')
        radius = np.array([0.5], 'f')
        host = walking(clock, colliders=trunk, radii=radius)
        # Face the trunk: the camera's forward at yaw 0 is -z.
        press(host, 'w')
        run(host, clock, 4.0)
        x, _y, z = eye(host)
        assert math.hypot(x - 0.0, z + 6.0) >= 0.5 + host.player_radius - 0.02
        assert z > -6.0

    def test_open_ground_is_not_obstructed(self, clock):
        host = walking(clock, colliders=np.zeros((0, 3), 'f'), radii=np.zeros(0, 'f'))
        press(host, 'w')
        run(host, clock, 1.0)
        assert eye(host)[2] < -1.0

    def test_a_trunk_stops_a_walker_and_not_a_flier(self, clock):
        trunk = np.array([[0.0, 0.0, -6.0]], 'f')
        host = walking(clock, colliders=trunk, radii=np.array([0.5], 'f'))
        host.togglePhysicsFly()
        press(host, 'w')
        run(host, clock, 4.0)
        assert eye(host)[2] < -7.0


class TestMounds:
    """A rock the walker can step onto is walked up, over and off; one too tall is a wall."""

    @staticmethod
    def mound(rim, top, radius=1.5, at=(0.0, 0.0, -6.0)):
        positions = np.array([at], 'f')
        arrays = (positions, np.array([radius], 'f'), np.array([rim], 'f'), np.array([top], 'f'))
        return lambda _x, _z, _reach: arrays

    def host_walking_at(self, clock, source):
        host = walking(clock, field=flat_field(height=0.0))
        host.add_collider_source(source)
        press(host, 'w')
        return host

    def feet(self, host):
        return eye(host)[1] - host.eye_height

    def test_the_walker_climbs_onto_a_rock_it_can_step_onto_and_goes_over_it(self, clock):
        host = self.host_walking_at(clock, self.mound(rim=0.1, top=0.4))
        highest, passed = 0.0, False
        for _ in range(60 * 6):
            run(host, clock, FRAME, FRAME)
            highest = max(highest, self.feet(host))
            passed = passed or eye(host)[2] < -8.0
        assert highest > 0.35
        assert passed

    def test_the_walker_stands_on_top_of_the_rock_it_climbed(self, clock):
        host = self.host_walking_at(clock, self.mound(rim=0.1, top=0.4, radius=3.0))
        run(host, clock, 3.0)
        press(host, 'w', state=0)
        run(host, clock, 0.5)
        x, y, z = eye(host)
        assert math.hypot(x, z + 6.0) < 3.0
        assert y - host.eye_height == pytest.approx(
            0.1 + 0.3 * math.sqrt(1.0 - (math.hypot(x, z + 6.0) / 3.0) ** 2), abs=0.02)

    def test_a_rock_too_tall_to_step_onto_is_a_wall(self, clock):
        host = self.host_walking_at(clock, self.mound(rim=0.9, top=1.4))
        run(host, clock, 6.0)
        x, y, z = eye(host)
        assert math.hypot(x, z + 6.0) >= 1.5 + host.player_radius - 0.03
        assert y - host.eye_height == pytest.approx(0.0, abs=2e-3)

    def test_a_walker_whose_feet_are_above_the_rock_is_not_stopped_by_it(self, clock):
        host = walking(clock, field=flat_field(height=0.0))
        host.add_collider_source(self.mound(rim=0.9, top=1.4))
        run(host, clock, 0.2)
        walker = host.physicsPlatform.managed
        walker.teleport((0.0, 2.0, -6.0))
        assert tuple(walker.position[::2]) == pytest.approx((0.0, -6.0), abs=1e-3)
        assert walker.position[1] == pytest.approx(1.4, abs=0.02)

    def test_a_rock_is_a_body_of_the_world_while_the_walker_is_near_it(self, clock):
        host = walking(clock, field=flat_field(height=0.0))
        host.add_collider_source(self.mound(rim=0.1, top=0.4, at=(0.0, 0.0, -10.0)))
        run(host, clock, 0.2)
        assert host.physics.raycast((0.0, 5.0, -10.0), (0, -1, 0)).point[1] == pytest.approx(0.4, abs=0.02)

    def test_a_source_is_asked_where_the_walker_is_and_how_far_it_reaches(self, clock):
        asked = []

        def source(x, z, reach):
            asked.append((x, z, reach))
            return np.zeros((0, 3), 'f'), np.zeros(0, 'f')

        host = walking(clock)
        host.add_collider_source(source)
        run(host, clock, 0.2)
        assert asked[0][:2] == pytest.approx((0.0, 0.0), abs=0.1)
        assert asked[0][2] >= host.collider_reach


class TestFlying:
    def test_flying_leaves_the_ground(self, clock):
        host = walking(clock)
        host.togglePhysicsFly()
        press(host, ' ')                      # rise
        run(host, clock, 1.0)
        x, y, z = eye(host)
        assert y > host._tw_hf.height_at(x, z) + host.eye_height + 1.0  # noqa: SLF001 the height field the walk mixin holds, which it does not expose

    def test_the_ground_is_still_a_floor_while_flying(self, clock):
        host = walking(clock)
        host.togglePhysicsFly()
        press(host, 'c')                      # sink
        run(host, clock, 2.0)
        x, y, z = eye(host)
        assert y >= host._tw_hf.height_at(x, z) + host.eye_height - 1e-6  # noqa: SLF001 the height field the walk mixin holds, which it does not expose

    def test_a_rock_is_a_floor_under_a_flier(self, clock):
        host = walking(clock, field=flat_field(height=0.0))
        host.add_collider_source(TestMounds.mound(rim=0.3, top=0.8, radius=3.0, at=(0.0, 0.0, -2.0)))
        host.togglePhysicsFly()
        press(host, 'c')
        run(host, clock, 2.0)
        surface = 0.3 + 0.5 * math.sqrt(1.0 - (2.0 / 3.0) ** 2)      # the dome, 2 m from its middle
        assert eye(host)[1] - host.eye_height == pytest.approx(surface, abs=0.02)


class TestJumping:
    def test_a_jump_leaves_the_ground_and_lands_again(self, clock):
        host = walking(clock)
        press(host, ' ')
        run(host, clock, 3.0 / 60.0)
        press(host, ' ', state=0)
        x, y, z = eye(host)
        assert y > host._tw_hf.height_at(x, z) + host.eye_height  # noqa: SLF001 the height field the walk mixin holds, which it does not expose
        run(host, clock, 2.0)
        x, y, z = eye(host)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,  # noqa: SLF001 the height field the walk mixin holds, which it does not expose
                                  abs=2e-3)


# -- living beside the free-fly camera ----------------------------------------

class TestFreeFly:
    def test_the_cascade_clamp_leaves_the_avatar_alone(self, clock):
        """While the avatar owns the camera, the free-fly clamp must not fight it."""
        host = walking(clock)
        press(host, ' ')                      # mid-jump: above the ground
        run(host, clock, 3.0 / 60.0)
        airborne = eye(host)
        host.collide_and_clamp()
        assert eye(host) == pytest.approx(airborne)

    def test_the_cascade_clamp_still_holds_the_free_fly_camera_down(self, clock):
        host = clock.host((3.0, 999.0, -2.0))
        host.init_walk(flat_field(height=5.0))
        host.collide_and_clamp()
        assert eye(host)[1] == pytest.approx(5.0 + host.eye_height, abs=2e-3)

    def test_handing_the_camera_back_and_taking_it_again(self, clock):
        host = walking(clock)
        manager = host._freeManager  # noqa: SLF001 the free-flying manager the walk mixin sets aside, which it does not expose
        host.togglePhysics()
        assert host.physicsWalking is False and manager.bound is True
        host.platform.setPosition((10.0, 400.0, 10.0))
        host.togglePhysics()
        assert host.physicsWalking is True
        run(host, clock, 0.2)
        x, y, z = eye(host)
        assert (x, z) == pytest.approx((10.0, 10.0), abs=1e-3)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,  # noqa: SLF001 the height field the walk mixin holds, which it does not expose
                                  abs=2e-3)

    def test_the_avatar_is_not_stepped_while_the_camera_is_free(self, clock):
        host = walking(clock)
        host.togglePhysics()
        assert host.physicsPlatform.managed.framed is False
        host.togglePhysics()
        assert host.physicsPlatform.managed.framed is True


class TestBeforeAnyTerrain:
    """Nothing is bound until :meth:`init_walk`, and until then nothing happens.

    A context can mix this in and decide later whether it has a landscape --
    a scene still loading, a viewer that opened a model instead -- so every
    entry point has to be harmless with no height field behind it.
    """

    def test_walking_is_refused_with_no_terrain_to_walk(self, clock):
        host = clock.host()
        assert host.setupPhysics(enable=True) is False
        assert host.physicsWalking is False
        assert host.movementManager is not None

    def test_placing_and_resolving_are_harmless(self, clock):
        host = clock.host()
        host.spawnAvatar(None, None, None)
        host.syncAvatarToCamera()
        host.standAvatarOnTerrain()
        host.resolveTerrain()
        assert host.physicsPlatform is None

    def test_a_bound_avatar_with_the_terrain_taken_away_is_left_where_it_is(self, clock):
        host = walking(clock)
        controller = host.physicsPlatform.character
        controller.position[:] = (3.0, -40.0, 7.0)   # well under the old ground
        controller.vy = -2.0
        controller.grounded = False
        host._tw_hf = None  # noqa: SLF001 the height field the walk mixin holds, which it does not expose
        host.standAvatarOnTerrain()
        host.resolveTerrain()
        assert tuple(controller.position) == (3.0, -40.0, 7.0)
        assert controller.vy == -2.0 and controller.grounded is False


class TestIdle:
    def test_idle_still_streams_as_the_walker_moves(self, clock):
        host = walking(clock)
        seen = []
        host.add_stream(1.0, lambda x, z: seen.append((x, z)))
        host.OnIdle()
        assert len(seen) == 1                 # fires once on the first frame
        press(host, 'w')
        run(host, clock, 1.0)
        host.OnIdle()
        assert len(seen) == 2


def test_a_host_made_with_a_different_height_field_walks_that_one(clock):
    host = clock.host()
    host.init_walk(flat_field(height=5.0))
    host.init_walk(HeightField(np.ones((8, 8)), 200.0, 9.0))
    host.setupPhysics(enable=True)
    run(host, clock, 0.3)
    assert eye(host)[1] == pytest.approx(9.0 + host.eye_height, abs=2e-3)
    assert host.physics.raycast((10.0, 50.0, 10.0), (0, -1, 0)).point[1] == pytest.approx(9.0, abs=0.01)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
