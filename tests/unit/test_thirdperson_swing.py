"""A follow camera that swings round behind the way its character is going."""
import math
from types import SimpleNamespace

import pytest

from OpenGLContext.move.thirdperson import ThirdPersonPlatform
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
FRAME = 1 / 60


class Camera:
    def __init__(self):
        self.position = None

    def setPosition(self, position):
        self.position = position

    def setOrientation(self, orientation):
        pass


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0))
    service.add_static(surfaces.shape(surfaces.block((80, 1, 80)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box')
    yield service
    service.close()


def walk(physics, platform, seconds):
    camera = platform.camera.platform
    for _ in range(int(round(seconds / FRAME))):
        physics.frame(FRAME)
        platform.update(FRAME)
        platform.apply(SimpleNamespace(platform=camera))


def test_the_camera_swings_behind_a_character_walking_along_x(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    platform = ThirdPersonPlatform.over(me, camera=Camera(), swing=0.4)
    me.set_move((1, 0, 0), 'run')
    walk(physics, platform, 3.0)
    assert platform.yaw == pytest.approx(math.pi / 2, abs=0.05)      # looking along +x


def test_the_swing_takes_about_the_seconds_it_is_given(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    slow = ThirdPersonPlatform.over(me, camera=Camera(), swing=2.0)
    me.set_move((1, 0, 0), 'run')
    walk(physics, slow, 1.0)
    assert 0.2 < slow.yaw < math.pi / 2 - 0.3


def test_a_standing_character_leaves_the_camera_where_it_is(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    platform = ThirdPersonPlatform.over(me, yaw=1.0, camera=Camera(), swing=0.4)
    walk(physics, platform, 1.0)
    assert platform.yaw == pytest.approx(1.0)


def test_the_camera_turns_the_short_way_round(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    platform = ThirdPersonPlatform.over(me, yaw=-math.pi + 0.3, camera=Camera(), swing=0.2)
    me.set_move((0.2, 0, 1.0), 'run')        # nearly along +z: a yaw of pi - 0.2
    wanted = math.atan2(0.2, -1.0)
    seen = []
    camera = platform.camera.platform
    for _ in range(120):
        physics.frame(FRAME)
        platform.update(FRAME)
        platform.apply(SimpleNamespace(platform=camera))
        seen.append(platform.yaw)
    assert abs(math.remainder(platform.yaw - wanted, 2 * math.pi)) < 0.05
    assert min(abs(yaw) for yaw in seen) > 2.5                     # it never swung through zero


def test_without_a_swing_the_yaw_is_the_keys_alone(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    platform = ThirdPersonPlatform.over(me, camera=Camera())
    me.set_move((1, 0, 0), 'run')
    walk(physics, platform, 1.0)
    assert platform.yaw == 0.0
