"""X3D's ParticleSystem drawn: each geometry type, through each renderer.

A system of particles held at the origin, in front of the default viewpoint,
is drawn as quads, triangles, sprites, lines, points and copies of a box, by
the PBR and the VRML97 renderers and in the compatibility profile, and the
middle of the picture is the appearance's colour. A frame of a running system
makes no GL objects and compiles nothing.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.x3dparticles import (
    ExplosionEmitter, ParticleSystem, PointEmitter,
)
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context
from OpenGLContext.testing.stillframe import check_still_frame



def _red(**named):
    return basenodes.Appearance(material=basenodes.Material(
        diffuseColor=(1, 0, 0), emissiveColor=(1, 0, 0)), **named)


def _system(kind):
    """A system of ``kind`` whose particles sit at the origin"""
    common = dict(maxParticles=40, particleLifetime=100.0, lifetimeVariation=0.0,
                  appearance=_red())
    if kind == 'LINE':
        return ParticleSystem(geometryType='LINE', particleSize=(0.1, 6.0),
                              emitter=ExplosionEmitter(speed=0.01, variation=0.0), **common)
    if kind == 'POINT':
        common['appearance'] = _red(pointProperties=x3d.PointProperties(
            pointSizeScaleFactor=12, pointSizeMaxValue=12))
        return ParticleSystem(geometryType='POINT', emitter=ExplosionEmitter(), **common)
    if kind == 'GEOMETRY':
        return ParticleSystem(geometryType='GEOMETRY', geometry=basenodes.Box(size=(3, 3, 3)),
                              emitter=ExplosionEmitter(), **common)
    return ParticleSystem(geometryType=kind, particleSize=(3.0, 3.0),
                          emitter=ExplosionEmitter(), **common)


def _drawn(system, environment):
    with scene_context([system], environment=environment) as context:
        for _ in range(2):
            context.renderQueue.run()
            context.OnDraw(force=1)
        context.renderQueue.run()
        return drawn_image(context)


def _centre(image):
    height, width = image.shape[:2]
    return image[height // 2 - 2:height // 2 + 3, width // 2 - 2:width // 2 + 3].reshape(-1, 3)


KINDS = ['QUAD', 'TRIANGLE', 'SPRITE', 'LINE', 'POINT', 'GEOMETRY']


@pytest.mark.parametrize('renderer', ['pbr', 'flat'])
@pytest.mark.parametrize('kind', KINDS)
def test_each_geometry_type_draws_in_its_appearances_colour(kind, renderer):
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    image = _drawn(_system(kind), {'OPENGLCONTEXT_RENDERER': renderer})
    centre = _centre(image).astype(int)
    reddest = centre[np.argmax(centre[:, 0] - centre[:, 1])]
    assert reddest[0] > 120 and reddest[1] < 60 and reddest[2] < 60, centre


@pytest.mark.parametrize('kind', ['QUAD', 'SPRITE', 'GEOMETRY'])
def test_the_compatibility_profile_draws_them_too(kind):
    refused = profile_unavailable('compatibility')
    if refused:
        pytest.skip(refused)
    image = _drawn(_system(kind), {'OPENGLCONTEXT_PROFILE': 'compatibility'})
    centre = _centre(image).astype(int)
    assert (centre[:, 0] > 120).any() and (centre[:, 1] < 60).any(), centre


def test_a_colour_ramp_colours_each_particle():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    system = ParticleSystem(geometryType='QUAD', particleSize=(3.0, 3.0), maxParticles=4,
                            particleLifetime=100.0, colorKey=[0],
                            color=basenodes.Color(color=[(0, 0, 1)]),
                            emitter=ExplosionEmitter())
    centre = _centre(_drawn(system, {'OPENGLCONTEXT_RENDERER': 'pbr'})).astype(int)
    assert (centre[:, 2] > 200).all() and (centre[:, 0] < 40).all()


def test_a_running_system_makes_and_compiles_nothing_more():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    systems = [_system('SPRITE'), _system('GEOMETRY'),
               ParticleSystem(maxParticles=200, particleLifetime=2.0, appearance=_red(),
                              particleSize=(0.2, 0.2),
                              emitter=PointEmitter(speed=1.0))]
    with scene_context(systems, environment={'OPENGLCONTEXT_RENDERER': 'pbr'}) as context:
        def frame():
            context.renderQueue.run()
            context.OnDraw(force=1)
        # The two systems of sprites each stream their particles once a frame,
        # each a store orphaned and refilled, and the copies of the box, which
        # do not move, upload nothing.
        work = check_still_frame(frame, uploads=4, warmup=4)
    assert work.allocations == work.compiles == 0, work


@pytest.mark.parametrize('shape', ['sprite', 'line'])
def test_the_engines_emitter_draws_its_colour_ramp_as_sprites_or_streaks(shape):
    from OpenGLContext.scenegraph.particles import ParticleEmitter
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    emitter = ParticleEmitter(rate=0.0, burst=60, lifetime=100.0, lifetimeVariation=0.0,
                              speed=0.01, spread=3.1, gravity=(0, 0, 0), size=3.0, endSize=3.0,
                              sizeVariation=0.0, shape=shape, blending='alpha', seed=4,
                              colorKey=[0, 1], colorRamp=basenodes.Color(
                                  color=[(0, 1, 0), (0, 1, 0)]))
    centre = _centre(_drawn(emitter, {'OPENGLCONTEXT_RENDERER': 'pbr'})).astype(int)
    assert (centre[:, 1] > 100).any() and (centre[:, 0] < 40).all(), centre
