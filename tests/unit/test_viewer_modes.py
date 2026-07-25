"""The shipped viewers declare their movement modes.

Declared rather than hand-rolled means one settings screen can present the
navigation of every viewer, and a game embedding any of them can retune the
speeds by setting fields instead of subclassing.
"""

import pytest

from OpenGLContext.move import modes


def _names(declared):
    return [mode.name for mode in declared]


@pytest.mark.parametrize('module_name', [
    'OpenGLContext.bin.vrml_view',
    'OpenGLContext.bin.gltf_view',
])
def test_a_viewer_declares_walk_and_fly(module_name):
    module = __import__(module_name, {}, {}, ['movement_modes'])
    declared = module.movement_modes()
    assert 'walk' in _names(declared)
    assert 'fly' in _names(declared)


@pytest.mark.parametrize('module_name', [
    'OpenGLContext.bin.vrml_view',
    'OpenGLContext.bin.gltf_view',
])
def test_every_declared_mode_is_a_mode_node(module_name):
    module = __import__(module_name, {}, {}, ['movement_modes'])
    for mode in module.movement_modes():
        assert isinstance(mode, modes.MovementMode)
        assert mode.bindings
        assert all(binding.label for binding in mode.bindings)


@pytest.mark.parametrize('module_name', [
    'OpenGLContext.bin.vrml_view',
    'OpenGLContext.bin.gltf_view',
])
def test_the_modes_can_be_scaled_to_the_thing_being_viewed(module_name):
    """A viewer frames models of wildly different size, so the speeds are a
    parameter rather than a constant."""
    module = __import__(module_name, {}, {}, ['movement_modes'])
    small = [m for m in module.movement_modes(scale=1.0) if m.name == 'walk'][0]
    large = [m for m in module.movement_modes(scale=10.0) if m.name == 'walk'][0]
    assert large.walkSpeed == pytest.approx(small.walkSpeed * 10.0)


# -- the glTF viewer drives its walk through the declared modes ----------------

def test_the_gltf_viewer_offers_an_accelerating_turn():
    """`oglc-gltf` wants both a precise nudge and a quick spin in close
    quarters, which one steady rate cannot give."""
    from OpenGLContext.bin import gltf_view
    walk = [m for m in gltf_view.movement_modes() if m.name == 'walk'][0]
    assert walk.turnAcceleration > 1.0


def test_the_gltf_viewer_names_what_its_modes_drive():
    """Its modes move the character controller; the camera is where the
    controller ends up."""
    from OpenGLContext.bin import gltf_view
    context = gltf_view.TestContext.__new__(gltf_view.TestContext)
    context._physics_on = False
    context._physics = 'the-controller'
    context.platform = 'the-camera'
    assert context.getNavigationPlatform() == 'the-camera'
    context._physics_on = True
    assert context.getNavigationPlatform() == 'the-controller'


def test_the_gltf_viewer_declares_its_modes_scaled_to_the_model():
    """A model forty times the size needs speeds to match, and the viewer
    already computes that scale for its avatar."""
    from OpenGLContext.bin import gltf_view
    small = [m for m in gltf_view.movement_modes(scale=0.5) if m.name == 'fly'][0]
    large = [m for m in gltf_view.movement_modes(scale=5.0) if m.name == 'fly'][0]
    assert large.flySpeed == pytest.approx(small.flySpeed * 10.0)
