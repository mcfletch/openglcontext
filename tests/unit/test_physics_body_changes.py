"""A body's material, mass, friction and restitution changed after it was made.

Each change is a command, so it reaches a world stepped on its own thread as it
reaches an inline one; the body's own reads answer the new value at once.
"""
import time

import numpy as np
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.testing import physics as physics_testing

pytestmark = pytest.mark.engines('omi', 'jolt')


def make(mode):
    service = Physics(PhysicsDefinition(mode=mode, tickHz=120.0, maxCatchUp=1.0,
                                        gravity=(0.0, 0.0, 0.0), linearDamping=0.0))
    return service


@pytest.fixture(params=['inline', 'thread'])
def physics(request):
    service = make(request.param)
    yield service
    service.close()


def settle(physics, frames=3):
    """Let the world apply what was sent, in either mode."""
    for _ in range(frames):
        physics.frame(1 / 60)
        if physics.definition.mode == 'thread':
            physics.flush()
            time.sleep(1 / 60)
    physics_testing.settle(physics)
    physics.frame(0.0)


def column(physics, body, name):
    slot = {}

    def read(world):
        slot['value'] = np.array(getattr(world, name)[physics.worker.runtime.entry(body.uid).index])

    physics_testing.run(physics, read).result(5.0)
    return slot['value']


def crate(physics, mass=1.0):
    return physics.add_dynamic(None, proxy=Proxy.box((1.0, 2.0, 3.0)), mass=mass,
                               translation=(0, 5, 0))


def test_set_mass_changes_the_mass_and_the_inertia_of_the_shape(physics):
    body = crate(physics, mass=1.0)
    settle(physics)
    body.set_mass(4.0)
    assert body.mass == 4.0
    settle(physics)
    assert physics_testing.mass(physics, body) == pytest.approx(4.0)
    # A box's inertia about each axis is m (a^2 + b^2) / 12 over the other two sides.
    expected = 4.0 / 12.0 * np.array([2.0 ** 2 + 3.0 ** 2, 1.0 ** 2 + 3.0 ** 2, 1.0 ** 2 + 2.0 ** 2])
    if physics.engine.name == 'omi_physics':
        assert np.allclose(column(physics, body, 'inv_inertia'), 1.0 / expected)
    else:
        # Jolt has no inertia to read back: the spin an angular impulse gives is I^-1 L.
        body.set_angular_velocity((0.0, 0.0, 0.0))
        body.apply_torque_impulse((1.0, 0.0, 0.0))
        settle(physics, frames=1)
        assert body.angular_velocity[0] == pytest.approx(1.0 / expected[0], rel=0.05)


def test_an_impulse_after_set_mass_moves_the_body_by_impulse_over_the_new_mass(physics):
    body = crate(physics, mass=1.0)
    settle(physics)
    body.set_mass(8.0)
    body.apply_impulse((16.0, 0.0, 0.0))
    settle(physics)
    assert body.velocity[0] == pytest.approx(2.0, abs=1e-9)


def test_set_material_gives_the_body_the_material_and_its_coefficients(physics):
    body = crate(physics)
    body.set_material('rubber')
    assert body.material == 'rubber'
    assert (body.friction, body.restitution) == (0.9, 0.8)
    settle(physics)
    found = physics_testing.material(physics, body)
    assert (found.dynamicFriction, found.restitution) == pytest.approx((0.9, 0.8))


def test_set_material_takes_a_material_the_application_defined(physics):
    mud = physics.materials.define('mud', friction=0.95, restitution=0.0)
    body = crate(physics)
    body.set_material(mud)
    assert body.material == 'mud'
    assert body.friction == 0.95
    settle(physics)
    assert physics_testing.material(physics, body).staticFriction == pytest.approx(0.95)


def test_set_friction_and_set_restitution_change_one_coefficient_each(physics):
    body = crate(physics)
    body.set_material('wood')
    body.set_friction(0.1)
    body.set_restitution(0.7)
    assert body.material == 'wood'                     # the name, and the sound it carries, stay
    assert (body.friction, body.restitution) == (0.1, 0.7)
    settle(physics)
    material = physics_testing.material(physics, body)
    assert (material.staticFriction, material.dynamicFriction, material.restitution) == pytest.approx(
        (0.1, 0.1, 0.7))


def test_the_same_coefficients_share_one_material_in_the_world(physics):
    first, second = crate(physics), crate(physics)
    for _ in range(50):
        first.set_friction(0.3)
        second.set_friction(0.3)
    settle(physics)
    assert physics_testing.material_index(physics, first) == physics_testing.material_index(
        physics, second)
    assert physics_testing.material_count(physics) <= 2


def test_a_bouncier_material_bounces_higher():
    heights = {}
    for name in ('wood', 'rubber'):
        physics = Physics(PhysicsDefinition(mode='inline', tickHz=120.0))
        try:
            physics.add_static(None, proxy=Proxy.box((20.0, 1.0, 20.0)), translation=(0, -0.5, 0),
                               material='rubber')
            ball = physics.add_dynamic(None, proxy=Proxy.sphere(0.25), translation=(0, 2.0, 0))
            ball.set_material(name)
            top, falling = 0.0, True
            for _ in range(240):
                physics.frame(1 / 120)
                y = float(ball.position[1])
                if falling and ball.velocity[1] > 0.0:
                    falling = False
                if not falling:
                    top = max(top, y)
            heights[name] = top
        finally:
            physics.close()
    assert heights['rubber'] > heights['wood'] + 0.3


def test_values_that_cannot_be_are_refused(physics):
    body = crate(physics)
    floor = physics.add_static(None, proxy=Proxy.box((5.0, 1.0, 5.0)))
    zone = physics.add_trigger(None, proxy=Proxy.box((1.0, 1.0, 1.0)))
    for bad in (0.0, -1.0, float('nan')):
        with pytest.raises(ValueError, match='mass'):
            body.set_mass(bad)
    with pytest.raises(ValueError, match='dynamic'):
        floor.set_mass(5.0)
    for bad in (-0.1, float('inf')):
        with pytest.raises(ValueError, match='friction'):
            body.set_friction(bad)
        with pytest.raises(ValueError, match='restitution'):
            body.set_restitution(bad)
    with pytest.raises(ValueError, match='nonsense'):
        body.set_material('nonsense')
    with pytest.raises(ValueError, match='trigger'):
        zone.set_material('wood')
    floor.set_material('ice')                          # a static body takes a material
    assert floor.friction == 0.02


def test_a_floor_given_a_material_with_a_sound_plays_it_when_struck():
    from omi_audio import synth

    from OpenGLContext.testing.audio import RecordingAudio

    thud = synth.impact(0.2, seed=1)
    audio = RecordingAudio()
    physics = Physics(PhysicsDefinition(mode='inline', tickHz=120.0), audio=lambda: audio)
    try:
        physics.materials.define('moss', friction=0.8, restitution=0.0, sound=thud)
        floor = physics.add_static(None, proxy=Proxy.box((20.0, 1.0, 20.0)), translation=(0, -0.5, 0))
        physics.add_dynamic(None, proxy=Proxy.sphere(0.25), translation=(0, 1.0, 0))
        floor.set_material('moss')
        for _ in range(120):
            physics.frame(1 / 120)
        assert len(audio.played(thud)) >= 1
    finally:
        physics.close()


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_a_crate_made_heavy_after_it_was_added_blocks_a_walker(mode):
    physics = Physics(PhysicsDefinition(mode=mode, tickHz=120.0, maxCatchUp=1.0))
    try:
        physics.add_static(None, proxy=Proxy.box((60.0, 1.0, 60.0)), translation=(0, -0.5, 0))
        crate = physics.add_dynamic(None, proxy=Proxy.box((0.8, 0.8, 0.8)), mass=20.0,
                                    translation=(2.0, 0.4, 0.0))
        me = physics.add_character(position=(0, 0.05, 0))
        physics.frame(1 / 60)
        crate.set_mass(2000.0)                    # after the character's copy of the bodies is made
        for _ in range(150):
            me.set_move((1, 0, 0))
            physics.frame(1 / 60)
            if mode == 'thread':
                time.sleep(1 / 60)
        assert crate.position[0] == pytest.approx(2.0, abs=0.15)
        assert me.position[0] < 1.4
        assert me._controller.pushing is None      # the character's copy weighs it too
    finally:
        physics.close()
