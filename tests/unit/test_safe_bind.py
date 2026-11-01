"""Safe viewpoint binding: a camera bound low or inside geometry stands free (no GL)."""
import numpy as np
import pytest

from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.physics.character import capsule_proxy
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


@pytest.fixture
def physics():
    made = Physics(PhysicsDefinition(mode='inline'))
    yield made
    made.close()


def bound(physics, centre):
    """A walker bound with its capsule's centre at ``centre``, after half a second."""
    me = physics.add_character(position=(30.0, 0.0, 30.0))
    PhysicsViewPlatform(me).bind(centre)
    for _ in range(30):
        physics.frame(1 / 60)
    return me


def overlapped(physics, me):
    """What the walker's standing capsule overlaps, lifted 2 cm off the floor it stands on."""
    centre = np.asarray(me.position) + (0.0, me.capabilities.standHeight / 2.0 + 0.02, 0.0)
    return physics.overlap(capsule_proxy(me.capabilities), centre, skip=me.body)


def test_bind_inside_solid_box_depenetrates(physics):
    physics.add_static(None, Proxy.box((4, 4, 4)), translation=(0, 2, 0))   # solid y[0,4]
    me = bound(physics, (0, 2, 0))                     # bound at the block centre
    assert me.position[1] == pytest.approx(4.0, abs=0.05)   # raised onto its top
    assert overlapped(physics, me) == []


def test_bind_below_floor_snaps_base_onto_it(physics):
    physics.add_static(None, Proxy.box((60, 1, 60)), translation=(0, -0.5, 0))  # top at y=0
    me = bound(physics, (0, -0.2, 0))                  # camera authored below the floor
    assert me.position[1] == pytest.approx(0.0, abs=0.05)
    assert me.eye[1] == pytest.approx(me.position[1] + me.capabilities.eyeHeight, abs=1e-6)
    assert overlapped(physics, me) == []


def test_bind_slightly_high_snaps_down_to_floor(physics):
    physics.add_static(None, Proxy.box((60, 1, 60)), translation=(0, -0.5, 0))
    me = bound(physics, (0, 1.5, 0))                   # authored a bit above the floor
    assert me.grounded
    assert me.position[1] == pytest.approx(0.0, abs=0.05)
