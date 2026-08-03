"""Walking and flying are declared, not hand-rolled.

Declared modes mean one settings screen can present the navigation of every
viewer, and a game embedding one retunes the speeds by setting fields instead of
subclassing.  :func:`OpenGLContext.move.modes.walk_fly_modes` is the pair every
viewer offers -- there is one such declaration now, where each viewer used to
carry a copy of it (see ``plans/VIEWER-COMPONENT-EXTRACTION.md``).
"""

import pytest

from OpenGLContext.move import modes
from OpenGLContext.move.modes import walk_fly_modes


def _names(declared):
    return [mode.name for mode in declared]


def test_a_viewer_declares_walk_and_fly():
    declared = walk_fly_modes()
    assert 'walk' in _names(declared)
    assert 'fly' in _names(declared)


def test_every_declared_mode_is_a_mode_node():
    for mode in walk_fly_modes():
        assert isinstance(mode, modes.MovementMode)
        assert mode.bindings
        assert all(binding.label for binding in mode.bindings)


def test_the_modes_can_be_scaled_to_the_thing_being_viewed():
    """A viewer frames models of wildly different size, so the speeds are a
    parameter rather than a constant."""
    small = [m for m in walk_fly_modes(scale=1.0) if m.name == 'walk'][0]
    large = [m for m in walk_fly_modes(scale=10.0) if m.name == 'walk'][0]
    assert large.walkSpeed == pytest.approx(small.walkSpeed * 10.0)


def test_the_modes_offer_an_accelerating_turn():
    """A viewer wants both a precise nudge and a quick spin in close quarters,
    which one steady rate cannot give."""
    walk = [m for m in walk_fly_modes() if m.name == 'walk'][0]
    assert walk.turnAcceleration > 1.0


def test_flying_scales_with_the_model_too():
    """A model forty times the size needs speeds to match, and the avatar's own
    scale is what supplies it."""
    small = [m for m in walk_fly_modes(scale=0.5) if m.name == 'fly'][0]
    large = [m for m in walk_fly_modes(scale=5.0) if m.name == 'fly'][0]
    assert large.flySpeed == pytest.approx(small.flySpeed * 10.0)


def test_the_modes_match_the_avatar_they_drive():
    """The body starts at the figures it is about to be driven at.

    A mode hands its speed down with every move, so the two cannot drift once
    walking has begun -- but the avatar exists before the first mode has
    stepped, and it should not spend that frame at some other speed."""
    from OpenGLContext.move.physicswalk import PhysicsWalkMixin
    capabilities = PhysicsWalkMixin().characterCapabilities(2.0)
    walk, fly = walk_fly_modes(2.0)
    assert walk.walkSpeed == pytest.approx(capabilities.walkSpeed)
    assert walk.runSpeed == pytest.approx(capabilities.runSpeed)
    assert fly.flySpeed == pytest.approx(capabilities.flySpeed)


def test_a_world_you_are_inside_can_start_in_mouse_look():
    """The manager takes the first selectable mode, so first is what it starts in."""
    declared = walk_fly_modes(first_person=True)
    assert _names(declared) == ['fps', 'walk', 'fly']
    assert declared[0].capturePointer
    assert not walk_fly_modes()[0].capturePointer


def test_mouse_look_walks_at_the_same_speed_as_walking_does():
    """Taking the pointer changes how you steer, not how fast you go."""
    fps, walk, _fly = walk_fly_modes(3.0, first_person=True)
    assert fps.walkSpeed == pytest.approx(walk.walkSpeed)
    assert fps.runSpeed == pytest.approx(walk.runSpeed)


def test_the_gltf_viewer_names_what_its_modes_drive():
    """Its modes move the character controller; the camera is where the
    controller ends up."""
    from OpenGLContext.bin import view
    context = view.TestContext.__new__(view.TestContext)
    context.physicsWalking = False
    context.physicsPlatform = 'the-controller'
    context.platform = 'the-camera'
    assert context.getNavigationPlatform() == 'the-camera'
    context.physicsWalking = True
    assert context.getNavigationPlatform() == 'the-controller'
