"""Walking as a capability of any context (:mod:`OpenGLContext.move.physicswalk`).

These drive :class:`PhysicsWalkMixin` on a host that knows nothing about glTF and
has no GL: a real :class:`~omi_physics.world.PhysicsWorld` cooked from a real
scenegraph, a real character controller, and a stub for the handful of things the
mix-in asks of the context it is mixed into.  What is exercised is the capability
itself -- switching between the avatar and the free-fly camera, building the world
through the ``buildPhysicsWorld`` seam, standing the avatar on clear floor, moving
it to a defined view, and stepping it.
"""
import numpy as np
import pytest

from OpenGLContext.move import physicswalk
from OpenGLContext.move.physicswalk import PhysicsWalkMixin, yaw_from_orientation
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.transform import Transform


# -- worlds to walk in -------------------------------------------------------

def _quad(size=20.0, y=0.0):
    """A ``size`` x ``size`` floor quad centred on the origin at height ``y``."""
    h = size / 2.0
    return basenodes.Shape(geometry=basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[
            (-h, y, -h), (h, y, -h), (h, y, h), (-h, y, h)]),
        coordIndex=[0, 1, 2, 3, -1]))


def _floor_scene():
    return Transform(children=[_quad()])


def _huge_scene(size=400.0):
    """A world so large the avatar is taller than the floor-snap search reaches."""
    return Transform(children=[_quad(size=size)])


def _hollow_scene(gap=2.0, size=20.0):
    """A floor with nothing at all in the middle of it -- an open courtyard.

    The centre of a model's footprint is not always somewhere you can stand,
    which is the reason the spawn samples rather than assuming.
    """
    h = size / 2.0
    slabs = []
    for sign in (-1.0, 1.0):
        near, far = sign * gap, sign * h
        slabs.append(basenodes.Shape(geometry=basenodes.IndexedFaceSet(
            coord=basenodes.Coordinate(point=[
                (near, 0.0, -h), (far, 0.0, -h), (far, 0.0, h), (near, 0.0, h)]),
            coordIndex=[0, 1, 2, 3, -1])))
    return Transform(children=slabs)


# -- the smallest host the mix-in can be added to ----------------------------

class _Manager:
    """Stands in for the free-fly movement manager, recording bind/unbind."""

    def __init__(self):
        self.bound = True

    def bind(self, context):
        self.bound = True

    def unbind(self, context):
        self.bound = False


class _Platform:
    """A view platform the avatar can be seated at and read back from."""

    def __init__(self, position=(0.0, 0.0, 0.0)):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')
        from OpenGLContext import quaternion
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0)

    def setPosition(self, position):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')

    def setOrientation(self, orientation):
        from OpenGLContext import quaternion
        x, y, z, r = orientation
        self.quaternion = quaternion.fromXYZR(x, y, z, r)


class _Definition:
    movementModes = None
    movementMode = None


class _Host(PhysicsWalkMixin):
    """A context that has never heard of glTF, with walking mixed in."""

    def __init__(self, scene=None):
        self.sg = scene
        self.platform = _Platform()
        self.movementManager = _Manager()
        self.contextDefinition = _Definition()
        self.handlers = []
        self.redraws = 0
        self.modeChanges = 0

    def getViewPlatform(self):
        return self.platform

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, named.get('state'), function))

    def triggerRedraw(self, count):
        self.redraws += count

    def getNavigation(self):
        return None

    def updateNavigation(self, dt):
        pass

    def onPhysicsModeChanged(self):
        self.modeChanges += 1


def _started(scene=None):
    """A host with the toggle key bound and the free-fly manager remembered."""
    host = _Host(scene if scene is not None else _floor_scene())
    host.setupPhysics()
    return host


# -- the capability is present on every interactive context ------------------

class TestAvailableEverywhere:
    def test_view_platform_mixin_provides_walking(self):
        """Any context with a view platform can be asked to walk."""
        from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
        assert issubclass(ViewPlatformMixin, PhysicsWalkMixin)

    def test_a_context_that_never_walks_starts_switched_off(self):
        host = _Host(_floor_scene())
        assert host.physicsPlatform is None
        assert host.physicsWalking is False

    def test_setup_binds_the_toggle_key_and_remembers_the_free_navigator(self):
        host = _started()
        assert ('keyboard', 'g', 1, host.togglePhysics) in host.handlers
        assert host._freeManager is host.movementManager


# -- switching between the avatar and the free-fly camera --------------------

class TestEnableAndDisable:
    def test_enabling_hands_the_camera_to_the_avatar(self):
        host = _started()
        manager = host.movementManager
        assert host.enablePhysics(True) is True
        assert host.physicsWalking is True
        assert host.physicsPlatform is not None
        assert host.movementManager is None, 'the free navigator must let go'
        assert manager.bound is False

    def test_disabling_hands_the_camera_back(self):
        host = _started()
        manager = host.movementManager
        host.enablePhysics(True)
        host.enablePhysics(False)
        assert host.physicsWalking is False
        assert host.movementManager is manager
        assert manager.bound is True

    def test_toggling_alternates(self):
        host = _started()
        host.togglePhysics()
        assert host.physicsWalking is True
        host.togglePhysics()
        assert host.physicsWalking is False

    def test_a_scene_with_nothing_walkable_refuses_and_stays_free_fly(self):
        host = _started(Transform(children=[]))
        assert host.enablePhysics(True) is False
        assert host.physicsWalking is False
        assert host.physicsPlatform is None
        assert host.movementManager is not None

    def test_a_host_with_no_scenegraph_at_all_refuses(self):
        host = _Host(None)
        host.setupPhysics()
        assert host.enablePhysics(True) is False

    def test_setup_can_start_walking_immediately(self):
        host = _Host(_floor_scene())
        assert host.setupPhysics(enable=True) is True
        assert host.physicsWalking is True

    def test_mode_changes_are_announced_to_the_host(self):
        host = _started()
        host.enablePhysics(True)
        host.enablePhysics(False)
        assert host.modeChanges == 2

    def test_re_enabling_reseats_the_avatar_at_the_flown_to_camera(self):
        """Walking resumes from wherever free-fly left the camera."""
        host = _started()
        host.enablePhysics(True)
        host.enablePhysics(False)
        host.platform.setPosition((4.0, 3.0, -2.0))
        host.enablePhysics(True)
        eye = np.asarray(host.physicsPlatform.character.eye(), dtype='d')
        assert np.linalg.norm(eye[[0, 2]] - np.array([4.0, -2.0])) < 1.0


# -- the world is a seam ----------------------------------------------------

class TestBuildPhysicsWorldSeam:
    def test_default_cooks_the_world_from_the_scenegraph(self):
        host = _started()
        world, bounds = host.buildPhysicsWorld()
        lo, hi = bounds
        assert hi[0] - lo[0] == pytest.approx(20.0)
        assert world is not None

    def test_a_host_may_supply_a_world_it_built_itself(self):
        """A terrain or level context has its own world; it never comes from `sg`."""
        from OpenGLContext.physics.gltf_world import collision_world_from_scene
        built = collision_world_from_scene(_floor_scene())

        class _OwnWorld(_Host):
            def buildPhysicsWorld(self):
                return built

        host = _OwnWorld(None)          # no scenegraph at all
        host.setupPhysics()
        assert host.enablePhysics(True) is True
        assert host.physicsPlatform.character.world is built[0]

    def test_avatar_scale_follows_the_size_of_the_world(self):
        lo, hi = np.zeros(3), np.array([40.0, 10.0, 10.0])
        assert PhysicsWalkMixin.physicsAvatarScale(lo, hi) == pytest.approx(1.0)

    def test_a_degenerate_world_still_yields_a_usable_scale(self):
        zero = np.zeros(3)
        assert PhysicsWalkMixin.physicsAvatarScale(zero, zero) > 0.0

    def test_capabilities_scale_with_the_avatar(self):
        host = _Host(None)
        small = host.characterCapabilities(0.5)
        full = host.characterCapabilities(1.0)
        assert small.walkSpeed == pytest.approx(full.walkSpeed / 2.0)
        assert small.eyeHeight == pytest.approx(full.eyeHeight / 2.0)

    def test_the_declared_movement_modes_are_scaled_to_the_avatar(self):
        host = _started()
        host.enablePhysics(True)
        modes = host.contextDefinition.movementModes
        assert [mode.name for mode in modes] == ['walk', 'fly']
        scale = host.physicsAvatarScale(*host.buildPhysicsWorld()[1])
        assert modes[0].walkSpeed == pytest.approx(3.0 * scale)


# -- finding somewhere to stand ---------------------------------------------

class TestSpawnAvatar:
    def test_the_avatar_ends_up_standing_on_the_floor(self):
        host = _started()
        host.enablePhysics(True)
        character = host.physicsPlatform.character
        assert character.grounded
        assert not character.stuck

    def test_a_centre_with_no_floor_under_it_is_avoided(self):
        """Nothing to stand on in the middle, so an open spot is found instead."""
        host = _started(_hollow_scene())
        host.enablePhysics(True)
        character = host.physicsPlatform.character
        assert abs(character.position[0]) > 2.0, 'spawned over the gap'
        assert character.grounded and not character.stuck

    def test_a_preferred_viewpoint_sets_the_initial_heading(self):
        class _Facing(_Host):
            def physicsSpawnViewpoints(self):
                return [basenodes.Viewpoint(position=(2.0, 1.6, 2.0),
                                            orientation=(0, 1, 0, 1.5))]

        host = _Facing(_floor_scene())
        host.setupPhysics()
        host.enablePhysics(True)
        assert host.physicsPlatform.yaw == pytest.approx(
            yaw_from_orientation((0, 1, 0, 1.5)))

    def test_the_host_may_pin_the_starting_heading(self):
        host = _started()
        host.physicsYaw = 0.75
        host.enablePhysics(True)
        assert host.physicsPlatform.yaw == pytest.approx(0.75)

    def test_the_most_open_spot_wins_when_none_is_fully_open(self, monkeypatch):
        """Nowhere is open on all four sides, so the best-scoring spot is taken.

        The probe is pinned here rather than built out of geometry: what is
        under test is the choice between candidates, and a world that makes a
        real capsule report a partial score has to be tuned to the avatar's
        size to the point where it tests the collision engine instead.
        """
        monkeypatch.setattr(physicswalk, '_clearance', lambda character, radius: 2)
        host = _started()
        host.enablePhysics(True)
        character = host.physicsPlatform.character
        assert character.grounded and not character.stuck
        # every candidate scored 2, so the tie went to the most central
        assert np.allclose(np.asarray(character.position)[[0, 2]], (0.0, 0.0),
                           atol=1e-6)

    def test_nowhere_to_stand_at_all_still_places_the_avatar(self):
        """No candidate reaches the floor, so the avatar goes to the middle anyway.

        Somewhere is better than nowhere: free-fly out is one keypress, while an
        unplaced avatar has no pose for the camera to take at all.
        """
        host = _started(_huge_scene())
        host.enablePhysics(True)
        position = np.asarray(host.physicsPlatform.character.position, dtype='d')
        assert not host.physicsPlatform.character.grounded
        assert np.allclose(position[[0, 2]], (0.0, 0.0), atol=1e-6)

    def test_it_is_a_no_op_before_the_avatar_exists(self):
        host = _started()
        host.spawnAvatar(np.zeros(3), np.ones(3), host.characterCapabilities())
        assert host.physicsPlatform is None


# -- moving the avatar to a defined view ------------------------------------

class TestMoveAvatarToViewpoint:
    def test_the_avatar_is_seated_at_the_viewpoint(self):
        host = _started()
        host.enablePhysics(True)
        viewpoint = basenodes.Viewpoint(position=(5.0, 1.6, -4.0),
                                        orientation=(0, 1, 0, 0.0))
        host.moveAvatarToViewpoint(viewpoint)
        eye = np.asarray(host.physicsPlatform.character.eye(), dtype='d')
        assert np.linalg.norm(eye[[0, 2]] - np.array([5.0, -4.0])) < 1.0
        assert host.physicsPlatform.pitch == pytest.approx(0.0)

    def test_the_heading_comes_from_the_viewpoint(self):
        host = _started()
        host.enablePhysics(True)
        host.moveAvatarToViewpoint(
            basenodes.Viewpoint(position=(0, 1.6, 0), orientation=(0, 1, 0, 0.8)))
        assert host.physicsPlatform.yaw == pytest.approx(
            yaw_from_orientation((0, 1, 0, 0.8)))

    def test_an_aerial_viewpoint_floats_rather_than_falls(self):
        """Nothing under a high camera, so the avatar flies there instead of plummeting."""
        host = _started()
        host.enablePhysics(True)
        host.moveAvatarToViewpoint(
            basenodes.Viewpoint(position=(0.0, 60.0, 0.0), orientation=(0, 1, 0, 0)))
        assert host.physicsPlatform.character.flying

    def test_it_is_a_no_op_before_the_avatar_exists(self):
        host = _started()
        host.moveAvatarToViewpoint(basenodes.Viewpoint())
        assert host.physicsPlatform is None


# -- the per-frame step -----------------------------------------------------

class TestStepPhysics:
    def test_stepping_drives_the_camera_from_the_avatar(self):
        host = _started()
        host.enablePhysics(True)
        host.platform.setPosition((0.0, 0.0, 0.0))
        host.stepPhysics(0.016)
        eye = np.asarray(host.physicsPlatform.character.eye(), dtype='d')
        assert np.allclose(np.asarray(host.platform.position[:3], dtype='d'), eye)

    def test_a_long_pause_does_not_teleport_the_avatar(self):
        """Wall-clock between frames is clamped, so a stall is not a giant step."""
        host = _started()
        host.enablePhysics(True)
        host._physicsLast -= 10.0
        before = np.asarray(host.physicsPlatform.character.position, dtype='d').copy()
        host.stepPhysics()
        after = np.asarray(host.physicsPlatform.character.position, dtype='d')
        assert np.linalg.norm(after - before) < 1.0

    def test_stepping_without_an_avatar_is_harmless(self):
        host = _started()
        host.stepPhysics(0.016)
        assert host.physicsPlatform is None

    def test_a_correction_hook_runs_before_the_camera_is_taken(self):
        """A host whose ground is not in the collision world corrects it here.

        Before the camera, so the view never shows the uncorrected pose: a
        height field walker lifted after ``apply`` would sink for one frame
        every frame.  See
        :meth:`OpenGLContext.move.terrainwalk.TerrainWalkMixin.resolveTerrain`.
        """
        host = _started()
        host.enablePhysics(True)
        lifted = float(host.physicsPlatform.character.position[1]) + 5.0

        def resolve():
            host.physicsPlatform.character.position[1] = lifted
        host.resolvePhysicsStep = resolve
        host.stepPhysics(0.016)
        assert float(host.physicsPlatform.character.position[1]) \
            == pytest.approx(lifted)
        eye = np.asarray(host.physicsPlatform.character.eye(), dtype='d')
        assert np.allclose(np.asarray(host.platform.position[:3], dtype='d'), eye)

    def test_the_correction_hook_does_nothing_by_default(self):
        host = _started()
        host.enablePhysics(True)
        assert host.resolvePhysicsStep() is None


# -- what the declared movement modes drive ---------------------------------

class TestNavigationPlatform:
    def test_the_camera_is_driven_while_free_flying(self):
        host = _started()
        assert host.getNavigationPlatform() is host.platform

    def test_the_avatar_is_driven_while_walking(self):
        host = _started()
        host.enablePhysics(True)
        assert host.getNavigationPlatform() is host.physicsPlatform


class TestYawFromOrientation:
    def test_an_unrotated_viewpoint_faces_negative_z(self):
        assert yaw_from_orientation((0, 1, 0, 0.0)) == pytest.approx(0.0)

    def test_a_node_rotation_reads_back_as_the_opposite_camera_yaw(self):
        """The two conventions are mirrored, which is the whole point of the function.

        A ``Viewpoint`` rotated by +r about +Y looks along ``(-sin r, 0, -cos r)``,
        while an avatar at yaw y faces ``(sin y, 0, -cos y)``; the same direction
        is therefore yaw ``-r``.
        """
        assert yaw_from_orientation((0, 1, 0, np.pi / 2)) == pytest.approx(
            -np.pi / 2, abs=1e-6)

    def test_the_heading_matches_the_direction_the_viewpoint_looks(self):
        for r in (0.0, 0.4, 1.2, -2.0, 3.0):
            yaw = yaw_from_orientation((0, 1, 0, r))
            looks = np.array([-np.sin(r), 0.0, -np.cos(r)])
            faces = np.array([np.sin(yaw), 0.0, -np.cos(yaw)])
            assert np.allclose(looks, faces, atol=1e-9), r


class _NavigatingHost(_Host):
    """A host with a real navigation manager over the declared movement modes."""

    navigation = None

    def getNavigation(self):
        from OpenGLContext.move.navigation import NavigationManager
        modes = getattr(self.contextDefinition, 'movementModes', None)
        if not modes:
            return None
        if self.navigation is None:
            self.navigation = NavigationManager(self.contextDefinition,
                                                self.getNavigationPlatform())
        else:
            self.navigation.retarget(self.getNavigationPlatform())
        return self.navigation


class TestMovementKeys:
    """Movement itself belongs to the declared modes; these are what is left.

    A key event only has to wake the frame loop -- the modes read the sampled
    input state, not the events -- and the fly key has to reach the character
    controller, since flying is a property of it and not of the movement.
    """

    def _walking(self):
        host = _NavigatingHost(_floor_scene())
        host.setupPhysics(enable=True)
        return host

    def test_the_keys_the_modes_name_are_claimed_for_walking(self):
        host = self._walking()
        claimed = {name for _kind, name, _state, _fn in host.handlers}
        assert {'w', 's', 'a', 'd', ' '} <= claimed
        assert host.physicsFlyKey in claimed

    def test_a_movement_key_only_wakes_the_frame_loop(self):
        host = self._walking()
        before = host.redraws
        host._physicsKey(None)
        assert host.redraws > before

    def test_the_fly_key_swaps_the_mode_and_tells_the_character(self):
        host = self._walking()
        host.togglePhysicsFly()
        assert host.contextDefinition.movementMode.name == 'fly'
        assert host.physicsPlatform.character.flying
        host.togglePhysicsFly()
        assert host.contextDefinition.movementMode.name == 'walk'
        assert not host.physicsPlatform.character.flying

    def test_the_fly_key_does_nothing_before_the_avatar_exists(self):
        host = _NavigatingHost(_floor_scene())
        host.setupPhysics()
        host.togglePhysicsFly()
        assert host.physicsPlatform is None

    def test_no_navigation_manager_means_no_keys_to_claim(self):
        host = _started()                       # getNavigation() returns None
        host.enablePhysics(True)
        assert not any(name == host.physicsFlyKey
                       for _kind, name, _state, _fn in host.handlers)


class TestBuiltOnlyOnce:
    def test_the_world_is_not_rebuilt_on_every_enable(self):
        host = _started()
        host.enablePhysics(True)
        avatar = host.physicsPlatform
        host.enablePhysics(False)
        host.enablePhysics(True)
        assert host.physicsPlatform is avatar
        assert host.ensurePhysicsWorld() is True


class TestSyncAvatarToCamera:
    def test_it_is_a_no_op_before_the_avatar_exists(self):
        host = _started()
        host.syncAvatarToCamera()
        assert host.physicsPlatform is None


class TestTheClock:
    def test_it_is_a_float(self):
        assert isinstance(PhysicsWalkMixin.physicsNow(), float)


class TestClearance:
    def test_open_ground_is_clear_in_every_direction(self):
        host = _started()
        host.enablePhysics(True)
        character = host.physicsPlatform.character
        assert physicswalk._clearance(character, 0.3) == 4
