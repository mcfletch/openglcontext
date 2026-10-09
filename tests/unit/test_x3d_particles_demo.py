"""``oglc-x3d-particles``: the X3D particle scene, with no window."""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_particles
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import x3dparticles
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

SYSTEMS = ('Brazier', 'Fountain', 'Firework', 'Snow', 'Sparks', 'Beads')


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_particles.ParticleScene(str(tmp_path_factory.mktemp('particles')))
    assert background.wait_for_idle(20.0)
    return found


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_images_it_names_are_written_beside_it(demo):
    assert {'x3d_particles.x3d', 'marble_base.png', 'sandstone_normal.png',
            'particle_sheet.png'} <= set(os.listdir(demo.directory))


def test_the_spark_sheet_is_two_frames_of_alpha():
    sheet = x3d_particles.spark_sheet(32)
    assert sheet.shape == (32, 64, 4)
    assert sheet[16, 16, 3] > 150 and sheet[0, 0, 3] == 0
    assert sheet[16, 48, 3] > 150 and sheet[2, 34, 3] == 0


def test_it_uses_every_emitter_and_physics_model(demo):
    systems = [demo.scene.getDEF(name) for name in SYSTEMS]
    assert all(isinstance(system, x3dparticles.ParticleSystem) for system in systems)
    emitters = {type(system.emitter) for system in systems}
    models = {type(model) for system in systems for model in system.physics}
    assert emitters == {x3dparticles.ConeEmitter, x3dparticles.PointEmitter,
                        x3dparticles.ExplosionEmitter, x3dparticles.PolylineEmitter,
                        x3dparticles.SurfaceEmitter, x3dparticles.VolumeEmitter}
    assert models == {x3dparticles.ForcePhysicsModel, x3dparticles.WindPhysicsModel,
                      x3dparticles.BoundedPhysicsModel}
    assert {system.geometryType for system in systems} == {
        'SPRITE', 'LINE', 'POINT', 'QUAD', 'GEOMETRY'}


def test_the_keys_fire_the_firework_and_switch_the_wind(demo):
    firework = demo.scene.getDEF('Firework')
    firework.advance(0.0)
    firework.advance(5.0)
    for step in range(1, 40):
        firework.advance(5.0 + step * 0.1)
    assert firework.particleCount == 0
    assert demo.press('f') == 'firework'
    firework.advance(9.0)
    assert firework.particleCount == firework.maxParticles
    assert demo.press('w') == 'wind off'
    assert demo.press('w') == 'wind on'
    assert demo.press('x') == ''


def test_every_system_draws(demo):
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    from OpenGLContext.video.clock import FixedStepClock
    with FixedStepClock(30, start=100.0) as clock, scene_context(
            demo.scene, size=(160, 90), environment={'OPENGLCONTEXT_RENDERER': 'pbr'}) as context:
        for _ in range(30):
            clock.advance()
            context.renderQueue.run()
            context.OnDraw(force=1)
        image = drawn_image(context)
    counts = {name: demo.scene.getDEF(name).particleCount for name in SYSTEMS}
    assert all(counts[name] for name in SYSTEMS if name != "Firework"), str(counts)
    assert image.astype(int).sum(axis=2).max() > 400
    assert np.count_nonzero(image.max(axis=2) > 30) > 0.05 * image.shape[0] * image.shape[1]
