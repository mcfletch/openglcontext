"""Movement speeds sized to the scene being moved through
(:mod:`OpenGLContext.viewer.sceneviewer`).

Fly and walk speeds are in scene units a second, so one constant cannot serve
both a chair and a city: at the small-scene default a 12 km dataset takes the
better part of an hour to cross, and nothing that streams while you move can be
seen happening. Speeds scale with the radius the viewer framed.
"""
import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move.modes import FLY_SPEED, WALK_SPEED, FlyMode
from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.sceneviewer import ViewerContext, MOVEMENT_REFERENCE_RADIUS


def _viewer(radius):
    viewer = ViewerContext.__new__(ViewerContext)
    viewer.options = ViewerOptions(source='model.glb')
    viewer.contextDefinition = ContextDefinition()
    viewer.radius = radius
    return viewer


def _speeds(viewer):
    return {mode.name: mode for mode in viewer.contextDefinition.movementModes}


class TestSpeedsFollowTheSceneSize:
    def test_a_small_scene_keeps_the_default_speeds(self):
        """A model-sized scene moves the way it always has."""
        viewer = _viewer(radius=4.0)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert _speeds(viewer)['fly'].flySpeed == pytest.approx(FLY_SPEED)
        assert _speeds(viewer)['walk'].walkSpeed == pytest.approx(WALK_SPEED)

    def test_a_city_sized_scene_is_flown_proportionally_faster(self):
        radius = MOVEMENT_REFERENCE_RADIUS * 100
        viewer = _viewer(radius=radius)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert _speeds(viewer)['fly'].flySpeed == pytest.approx(FLY_SPEED * 100)
        assert _speeds(viewer)['walk'].walkSpeed == pytest.approx(WALK_SPEED * 100)

    def test_crossing_a_scene_takes_a_watchable_number_of_seconds(self):
        """The scale is chosen for a traverse you can see, not a teleport."""
        radius = 7800.0                       # a 15 km city
        viewer = _viewer(radius=radius)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        seconds = 2 * radius / _speeds(viewer)['fly'].flySpeed
        assert 10.0 < seconds < 40.0, seconds

    def test_the_modes_a_host_declared_itself_are_left_alone(self):
        """Those are speeds somebody chose, at a scale we cannot re-derive."""
        viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
        viewer.contextDefinition.movementModes = [FlyMode(name='fly', flySpeed=2.0)]
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert _speeds(viewer)['fly'].flySpeed == pytest.approx(2.0)

    def test_the_same_mode_objects_are_retuned_rather_than_replaced(self):
        """Rebuilding the list would drop the mode the player is in."""
        viewer = _viewer(radius=4.0)
        viewer.declareMovementModes()
        before = list(viewer.contextDefinition.movementModes)
        viewer.radius = MOVEMENT_REFERENCE_RADIUS * 50
        viewer.scaleMovementSpeeds()
        assert list(viewer.contextDefinition.movementModes) == before
        assert before[1].flySpeed == pytest.approx(FLY_SPEED * 50)


class TestTheSettingsScreenFollowsTheSpeeds:
    def test_a_scaled_speed_is_inside_its_sliders_range(self):
        """A slider whose maximum is below the live speed would slow the
        session the moment anyone touched it."""
        viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        fly = _speeds(viewer)['fly']
        hint = fly.UI_HINTS['flySpeed']
        assert hint['minimum'] <= fly.flySpeed <= hint['maximum']

    def test_the_class_defaults_are_not_rewritten_for_everyone(self):
        viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert FlyMode.UI_HINTS['flySpeed']['maximum'] == 60.0

    def test_a_model_sized_scene_keeps_the_ranges_it_had(self):
        viewer = _viewer(radius=4.0)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert _speeds(viewer)['fly'].UI_HINTS is FlyMode.UI_HINTS


class TestTheFreeFlyStepFollowsTheSceneToo:
    """Free-fly does not go through the movement modes at all: a plain view
    platform has no body to tell a speed to, and the older manager steps a
    fixed distance per key. Unscaled, that is a quarter of a metre per press
    in a fifteen-kilometre city, however fast the settings screen says."""

    class _Manager:
        STEPDISTANCE = 0.25

    def test_the_step_grows_with_the_scene(self):
        viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
        viewer.movementManager = self._Manager()
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert viewer.movementManager.STEPDISTANCE == pytest.approx(25.0)

    def test_a_model_sized_scene_steps_as_it_always_did(self):
        viewer = _viewer(radius=4.0)
        viewer.movementManager = self._Manager()
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        assert viewer.movementManager.STEPDISTANCE == pytest.approx(0.25)

    def test_scaling_twice_does_not_compound(self):
        """Framing a second scene retunes from the default, not from the last
        scaled value."""
        viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
        viewer.movementManager = self._Manager()
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()
        viewer.scaleMovementSpeeds()
        assert viewer.movementManager.STEPDISTANCE == pytest.approx(25.0)

    def test_no_manager_yet_is_not_an_error(self):
        viewer = _viewer(radius=100.0)
        viewer.declareMovementModes()
        viewer.scaleMovementSpeeds()          # nothing bound yet: mounts first


def test_a_manager_bound_after_the_scene_is_scaled_when_it_arrives():
    """The order the two happen in is not fixed, and either way round the
    stepping has to match the world."""
    viewer = _viewer(radius=MOVEMENT_REFERENCE_RADIUS * 100)
    viewer.declareMovementModes()
    viewer.scaleMovementSpeeds()

    class _Manager:
        STEPDISTANCE = 0.25

        def bind(self, context):
            pass

        def unbind(self, context):
            pass

    viewer.setMovementManager(_Manager())
    assert viewer.movementManager.STEPDISTANCE == pytest.approx(25.0)
