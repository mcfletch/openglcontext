"""Switching to walking drops the avatar where the camera is
(:mod:`OpenGLContext.move.physicswalk`).

Spawning searches the middle of the world for somewhere open, which is right
for a model you have just opened and wrong the moment the world is a city: the
camera is wherever you flew to, and the middle of a twelve-kilometre dataset is
several kilometres away -- often over water. Walking from there back to what
you were looking at is a twenty-minute walk, so the camera's own position is
tried first and the search is what happens when it will not do.
"""
import numpy as np
import pytest

from omi_physics import model
from omi_physics.world import PhysicsWorld
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform


def _ground_world(size=6000.0):
    """A flat floor spanning `size` metres, the way a city's ground reads."""
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    half = size / 2
    points = np.array([[-half, 0.0, -half], [half, 0.0, -half],
                       [half, 0.0, half], [-half, 0.0, half]], dtype='d')
    indices = np.array([[0, 2, 1], [0, 3, 2]])
    shape = world.add_shape(model.Shape.trimesh(points, indices))
    world.add_body(model.Motion(type=model.STATIC),
                   collider=model.Collider(shape=shape))
    return world, (np.array([-half, 0.0, -half]), np.array([half, 0.0, half]))


class _Walker:
    """The little of a walking context `spawnAvatar` uses."""

    from OpenGLContext.move.physicswalk import PhysicsWalkMixin
    spawnAvatar = PhysicsWalkMixin.spawnAvatar

    def __init__(self, platform):
        self.physicsPlatform = platform


def _capabilities():
    from omi_physics.character import CharacterCapabilities
    return CharacterCapabilities(standHeight=1.8, eyeHeight=1.6, radius=0.3,
                                 crouchHeight=1.0, stepHeight=0.4)


def test_the_avatar_lands_under_the_camera():
    world, (low, high) = _ground_world()
    platform = PhysicsViewPlatform(world, _capabilities())
    walker = _Walker(platform)
    walker.spawnAvatar(low, high, _capabilities(), preferred=(2200.0, 40.0, -1750.0))
    landed = platform.character.position
    assert landed[0] == pytest.approx(2200.0, abs=1.0)
    assert landed[2] == pytest.approx(-1750.0, abs=1.0)


def test_a_camera_over_nothing_falls_back_to_the_search():
    """Off the edge of the world there is nothing to stand on; the search still
    finds the floor rather than leaving the avatar in the void."""
    world, (low, high) = _ground_world()
    platform = PhysicsViewPlatform(world, _capabilities())
    walker = _Walker(platform)
    walker.spawnAvatar(low, high, _capabilities(), preferred=(90000.0, 40.0, 90000.0))
    landed = platform.character.position
    assert abs(landed[0]) <= 3000.0 and abs(landed[2]) <= 3000.0


def test_without_a_preference_it_spawns_as_it_always_did():
    world, (low, high) = _ground_world()
    platform = PhysicsViewPlatform(world, _capabilities())
    walker = _Walker(platform)
    walker.spawnAvatar(low, high, _capabilities())
    assert platform.character.grounded
