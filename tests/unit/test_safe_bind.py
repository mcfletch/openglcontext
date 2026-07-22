"""Phase 5 safe viewpoint binding: never spawn stuck in geometry (no GL)."""
import numpy as np
import pytest

from omi_physics import model
from omi_physics.world import PhysicsWorld
from omi_physics.character import CharacterController, CharacterCapabilities


def add_box(world, size, center):
    shape = world.add_shape(model.Shape.box(size))
    return world.add_body(model.Motion(type=model.STATIC),
                          collider=model.Collider(shape=shape), position=center)


def test_bind_inside_solid_box_depenetrates():
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81))
    add_box(world, (4, 4, 4), (0, 2, 0))           # solid block spanning y[0,4]
    ch = CharacterController(world, CharacterCapabilities(), gravity=9.81)
    ok = ch.safe_bind((0, 2, 0))                    # bound at the block centre
    assert ok
    assert not ch.stuck
    assert not ch._overlaps(ch._proxy())            # pushed out to free space


def test_bind_below_floor_snaps_base_onto_it():
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81))
    add_box(world, (60, 1, 60), (0, -0.5, 0))       # floor top at y=0
    ch = CharacterController(world, CharacterCapabilities(), gravity=9.81)
    ch.safe_bind((0, -0.2, 0))                       # camera authored below the floor
    assert ch.base()[1] == pytest.approx(0.0, abs=0.05)
    eye = ch.eye()
    assert eye[1] == pytest.approx(ch.base()[1] + ch.caps.eyeHeight, abs=1e-6)
    assert not ch._overlaps(ch._proxy())


def test_bind_slightly_high_snaps_down_to_floor():
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81))
    add_box(world, (60, 1, 60), (0, -0.5, 0))
    ch = CharacterController(world, CharacterCapabilities(), gravity=9.81)
    ch.safe_bind((0, 1.5, 0))                        # authored a bit above the floor
    assert ch.grounded
    assert ch.base()[1] == pytest.approx(0.0, abs=0.05)


def test_no_free_space_falls_back_to_fly_without_wedging():
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81))
    add_box(world, (2, 4, 4), (-1.3, 2, 0))          # wall left of the gap
    add_box(world, (2, 4, 4), (1.3, 2, 0))           # wall right of the gap
    # gap width ≈ 0.6 < capsule diameter 0.6 → cannot fit
    ch = CharacterController(world, CharacterCapabilities(radius=0.4), gravity=9.81)
    ok = ch.safe_bind((0, 2, 0))
    assert ok is False
    assert ch.stuck
    assert ch.flying                                 # escaped into fly, not wedged


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
