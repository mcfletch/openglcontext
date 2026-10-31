"""oglc-cloth's and oglc-ragdoll's yards, driven without a window."""
import numpy as np
import pytest

from OpenGLContext.bin import cloth_demo, ragdoll_demo
from OpenGLContext.physics import Physics


def run(physics, yard, seconds, step=1 / 60):
    for _ in range(round(seconds / step)):
        yard.update(step)
        physics.frame(step)


def world(mesh):
    return mesh.positions.astype('d') + mesh.origin


@pytest.fixture
def cloth_yard():
    physics = Physics(cloth_demo.definition())
    yield physics, cloth_demo.ClothYard(physics)
    physics.close()


def test_the_banner_flies_from_its_pole_and_the_drape_rests_on_the_ball(cloth_yard):
    physics, yard = cloth_yard
    run(physics, yard, 2.0)
    banner = world(yard.banner.mesh)
    x = cloth_demo.POLE_FOOT[0]
    assert banner[:, 0].min() == pytest.approx(x + 0.06, abs=0.01)
    assert banner[:, 0].max() > x + 1.0
    drape = world(yard.drape.mesh)
    centre = np.asarray(cloth_demo.BALL_CENTRE)
    assert np.linalg.norm(drape - centre, axis=1).min() > cloth_demo.BALL_RADIUS - 0.02
    assert drape[:, 1].max() == pytest.approx(centre[1] + cloth_demo.BALL_RADIUS, abs=0.05)


def test_the_wind_steps_through_its_settings_and_still_air_lets_the_banner_hang(cloth_yard):
    physics, yard = cloth_yard
    assert [yard.next_wind() for _ in cloth_demo.WINDS] == ['still', 'gale', 'gusting']
    yard.next_wind()
    assert yard.wind_force(1.0) == (0.0, 0.0, 0.0)
    run(physics, yard, 4.0)
    banner = world(yard.banner.mesh)
    assert banner[:, 0].max() < cloth_demo.POLE_FOOT[0] + 0.6


def test_the_sheet_is_released_and_pinned_again_and_a_ball_strikes_it(cloth_yard):
    physics, yard = cloth_yard
    run(physics, yard, 0.5)
    assert not yard.toggle_sheet()
    run(physics, yard, 1.5)
    released = world(yard.sheet.mesh)[:, 1].min()
    assert yard.toggle_sheet()
    ball = yard.throw()
    run(physics, yard, 1.0)
    assert ball.position[2] < cloth_demo.BEAM[2] + 4.0
    assert released < cloth_demo.BEAM[1] - cloth_demo.SHEET[1] + 0.2


def test_dropping_the_drape_makes_a_new_one(cloth_yard):
    physics, yard = cloth_yard
    run(physics, yard, 0.5)
    old = yard.drape
    yard.drop()
    assert yard.drape is not old and not old.soft.alive
    meshes = [child.geometry for child in yard.root.children if hasattr(child, 'geometry')]
    assert old.mesh not in meshes and yard.drape.mesh in meshes
    assert len(yard.scene().children) == 4


def test_the_ragdoll_yard_strikes_knocks_down_and_gets_up():
    from test_character_ragdoll import BONES, figure

    class Model:
        def __init__(self):
            from OpenGLContext.scenegraph.basenodes import Transform
            self.mixer = figure(skin_radius=0.05)
            self.humanoid = type('H', (), {'bones': BONES})()
            self.group = Transform()
            self.clips = {}

    physics = Physics(ragdoll_demo.definition())
    try:
        yard = ragdoll_demo.RagdollYard(physics, Model())
        assert len(yard.scene().children) == 4
        run(physics, yard, 0.5)
        hips = yard.figure.ragdoll.bone('hips')
        yard.strike()
        run(physics, yard, 1.5)
        assert hips.position[1] > 0.8
        yard.knock_down()
        assert yard.down and yard.figure.ragdoll.mode.value == 'limp'
        run(physics, yard, 2.0)
        assert hips.position[1] < 0.4
        yard.get_up()
        run(physics, yard, 1.5)
        assert hips.position[1] > 0.85 and not yard.down
        assert yard.toggle_power() == 'kinematic'
        assert yard.toggle_power() == 'powered'
    finally:
        physics.close()
