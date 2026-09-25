"""Fire, smoke and sparks authored in a model rather than in Python.

An artist puts an empty where the torch is, tags the object ``fire`` in
Blender and exports; the file loads with a flame standing there. The three
kinds ship registered, so a tagged file needs no application code at all.

Each test writes a document with :mod:`OpenGLContext.loaders.gltf.writer` and
reads it back with :func:`OpenGLContext.loaders.gltf.load_gltf`. No GL: what
the tag makes is an emitter's fields, and those are numbers. Drawing one is
``test_gltf_particle_hooks_gl.py``.
"""
import logging

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph import particlehooks, particles
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape


def _box():
    """A small mesh, standing for the brazier a flame is burning in."""
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], 'f'),
        normals=np.array([(0, 1, 0)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=PBRMaterial(baseColor=(0.2, 0.2, 0.2)),
    )


def _walk(node, out=None):
    out = [] if out is None else out
    out.append(node)
    for child in getattr(node, 'children', None) or []:
        _walk(child, out)
    return out


def _emitters(scene):
    return [node for node in _walk(scene.group)
            if isinstance(node, particles.ParticleEmitter)]


def _loaded(hook, **named):
    """A document holding one node named ``torch`` carrying ``hook``."""
    scene = gltf.load_gltf(write_glb(SceneNode(name='torch', hook=hook, **named)))
    return scene, _emitters(scene)


# --- the kinds ship registered ------------------------------------------------

@pytest.mark.parametrize('kind', ['fire', 'smoke', 'sparks'])
def test_each_kind_is_bound_without_being_imported(kind):
    """A tagged file works in a viewer that never heard of particles."""
    assert hooks.registered(kind) is not None


# --- what a tag makes ---------------------------------------------------------

@pytest.mark.parametrize('kind', ['fire', 'smoke'])
def test_a_tagged_object_is_the_preset_it_names(kind):
    _scene, (emitter,) = _loaded({'kind': kind})
    for name in ('rate', 'lifetime', 'spread', 'drag', 'endAlpha'):
        assert getattr(emitter, name) == pytest.approx(particles.PRESETS[kind][name])
    assert emitter.blending == particles.PRESETS[kind]['blending']


def test_sparks_in_a_world_keep_coming():
    """The preset is one burst for a game to fire; a world wants a fountain."""
    _scene, (emitter,) = _loaded({'kind': 'sparks'})
    assert emitter.rate > 0.0
    assert emitter.burst == 0


def test_the_effect_stands_under_the_object_that_carries_it():
    """The node's own placement carries the flame, so moving the empty moves it."""
    scene, (emitter,) = _loaded({'kind': 'fire'}, translation=(4.0, 1.0, -2.0))
    torch = scene.getDEF('torch')
    assert emitter in _walk(torch)
    assert tuple(torch.translation) == pytest.approx((4.0, 1.0, -2.0))


def test_a_tagged_mesh_keeps_its_mesh():
    """A brazier tagged ``fire`` is still a brazier, with a flame in it."""
    scene, (emitter,) = _loaded({'kind': 'fire'}, mesh=_box())
    under = _walk(scene.getDEF('torch'))
    assert emitter in under
    assert any(isinstance(node, Shape) for node in under)


def test_the_emitter_lands_in_hook_data():
    scene, (emitter,) = _loaded({'kind': 'smoke'})
    assert scene.hook_data['smoke'] == [emitter]


# --- parameters ---------------------------------------------------------------

def test_any_emitter_field_may_be_given():
    """The panel's fields are a convenience; every authorable field is reachable."""
    _scene, (emitter,) = _loaded({'kind': 'smoke', 'rate': 5,
                                  'color': [0.8, 0.1, 0.1], 'lifetime': 9})
    assert emitter.rate == pytest.approx(5.0)
    assert tuple(emitter.color) == pytest.approx((0.8, 0.1, 0.1))
    assert emitter.lifetime == pytest.approx(9.0)


def test_scale_makes_the_whole_effect_bigger():
    """Twice the size, thrown twice as far, rising twice as fast: the same
    flame at twice the height, over the same lifetime."""
    _scene, (emitter,) = _loaded({'kind': 'fire', 'scale': 2.0})
    fire = particles.PRESETS['fire']
    assert emitter.size == pytest.approx(2.0 * fire['size'])
    assert emitter.endSize == pytest.approx(2.0 * fire['endSize'])
    assert emitter.speed == pytest.approx(2.0 * fire['speed'])
    assert tuple(emitter.gravity) == pytest.approx(
        tuple(2.0 * value for value in fire['gravity']))
    assert emitter.lifetime == pytest.approx(fire['lifetime'])


def test_scaling_the_object_scales_the_effect():
    """What an artist does in Blender to make a fire bigger."""
    _scene, (emitter,) = _loaded({'kind': 'fire', 'scale': 1.5},
                                 scale=(2.0, 2.0, 2.0))
    assert emitter.size == pytest.approx(3.0 * particles.PRESETS['fire']['size'])


def test_density_is_more_of_it():
    _scene, (emitter,) = _loaded({'kind': 'smoke', 'density': 3.0})
    smoke = particles.PRESETS['smoke']
    assert emitter.rate == pytest.approx(3.0 * smoke['rate'])
    assert emitter.maxParticles == 3 * smoke['maxParticles']


def test_a_parameter_that_is_no_field_is_passed_over(caplog):
    """A misspelling loads a fire rather than failing the file, and is said."""
    with caplog.at_level(logging.WARNING, logger=particlehooks.__name__):
        _scene, (emitter,) = _loaded({'kind': 'fire', 'raet': 5})
    assert emitter.rate == pytest.approx(particles.PRESETS['fire']['rate'])
    assert 'raet' in caplog.text


@pytest.mark.parametrize('given', ['big', -2.0, None])
def test_a_scale_that_is_no_positive_number_is_one(given, caplog):
    with caplog.at_level(logging.WARNING, logger=particlehooks.__name__):
        _scene, (emitter,) = _loaded({'kind': 'fire', 'scale': given})
    assert emitter.size == pytest.approx(particles.PRESETS['fire']['size'])
    assert 'scale' in caplog.text


def test_a_hook_run_without_a_world_matrix_is_unscaled():
    """A context an application builds for itself need not place anything."""
    ctx = hooks.HookContext(at='node', kind='smoke', params={}, document=None,
                            resolver=None, scene_data={})
    emitter, replacing = particlehooks.particle_hook(ctx)
    assert replacing is False
    assert emitter.size == pytest.approx(particles.PRESETS['smoke']['size'])


def test_a_value_the_field_will_not_take_is_passed_over(caplog):
    with caplog.at_level(logging.WARNING, logger=particlehooks.__name__):
        _scene, (emitter,) = _loaded({'kind': 'fire', 'rate': 'lots',
                                      'size': 0.8})
    assert emitter.rate == pytest.approx(particles.PRESETS['fire']['rate'])
    assert emitter.size == pytest.approx(0.8)
    assert 'lots' in caplog.text


# --- where it may stand -------------------------------------------------------

def test_on_a_material_it_does_nothing():
    """A flame stands somewhere; a surface is not a place."""
    material = PBRMaterial(baseColor=(0.2, 0.2, 0.2))
    material.hook = {'kind': 'fire'}
    mesh = _box()
    mesh.material = material
    scene = gltf.load_gltf(write_glb(SceneNode(mesh=mesh)))
    assert _emitters(scene) == []
    assert 'fire' not in scene.hook_data


def test_switched_off_the_tag_is_left_unread(monkeypatch):
    monkeypatch.setenv(hooks.ENVIRONMENT, '0')
    scene, emitters = _loaded({'kind': 'fire'})
    assert emitters == []


# --- time ---------------------------------------------------------------------

def test_a_burning_scene_asks_to_be_redrawn():
    """An emitter steps itself as it is drawn; the viewer has to keep drawing."""
    scene, _emitter = _loaded({'kind': 'fire'})
    assert scene.advance(0.5) is True


def test_a_spent_effect_asks_for_nothing():
    scene, (emitter,) = _loaded({'kind': 'smoke'})
    emitter.enabled = False
    assert scene.advance(0.5) is False


# --- a file the application does not control -------------------------------------

CEILINGS = {'rate': 2000.0, 'maxParticles': 20000, 'burst': 20000,
            'size': 20.0, 'endSize': 20.0, 'speed': 100.0}


@pytest.mark.parametrize('hook', [
    {'kind': 'fire', 'density': 1e7},
    {'kind': 'fire', 'maxParticles': 4e9},
    {'kind': 'sparks', 'burst': 10 ** 12, 'rate': 1e30},
    {'kind': 'fire', 'scale': 1e9},
    {'kind': 'fire', 'size': 1e6, 'speed': 1e6},
    {'kind': 'fire', 'density': 1e300, 'scale': 1e300},
])
def test_no_tag_asks_for_more_than_the_fields_ceilings(hook):
    """A file cannot size the particle pool, or a particle, past what the
    emitter's own fields declare as their range."""
    _scene, (emitter,) = _loaded(hook)
    for name, ceiling in CEILINGS.items():
        assert getattr(emitter, name) <= ceiling, name
    assert np.all(np.isfinite(emitter.gravity))


@pytest.mark.parametrize('name, value', [
    ('rate', float('inf')), ('lifetime', float('nan')), ('spread', 'nan'),
    ('size', -1.0), ('color', [1.0, 'x', 0.0]), ('gravity', [0, float('inf'), 0]),
    ('blending', 'glitter'), ('enabled', 'maybe'), ('seed', 2 ** 40),
])
def test_a_value_no_emitter_can_have_is_its_preset_or_its_bound(name, value):
    _scene, (emitter,) = _loaded({'kind': 'fire', name: value})
    got = getattr(emitter, name)
    assert np.all(np.isfinite(np.asarray(got, dtype='d'))) if name != 'blending' \
        else got in ('additive', 'alpha')
    if name == 'size':
        assert emitter.size == 0.0
    if name == 'seed':
        assert -1 <= emitter.seed < 2 ** 31


@pytest.mark.parametrize('texture', ['/etc/hostname', '../outside.png',
                                     '../../etc/passwd'])
def test_a_sprite_outside_the_documents_directory_is_refused(tmp_path, texture, caplog):
    path = tmp_path / 'torch.glb'
    write_glb(SceneNode(name='torch', hook={'kind': 'fire', 'texture': texture}),
              path=str(path))
    with caplog.at_level(logging.WARNING):
        emitter, = _emitters(gltf.load_gltf(str(path)))
    assert emitter.texture == ''
    assert 'texture' in caplog.text


def test_a_sprite_from_a_document_loaded_from_bytes_is_refused():
    """With no directory to read beside, there is nowhere the path could mean."""
    _scene, (emitter,) = _loaded({'kind': 'fire', 'texture': 'spark.png'})
    assert emitter.texture == ''


def test_a_sprite_beside_the_document_is_read_from_there(tmp_path):
    (tmp_path / 'spark.png').write_bytes(b'')
    path = tmp_path / 'torch.glb'
    write_glb(SceneNode(name='torch', hook={'kind': 'fire', 'texture': 'spark.png'}),
              path=str(path))
    emitter, = _emitters(gltf.load_gltf(str(path)))
    assert emitter.texture == str(tmp_path / 'spark.png')


def test_the_emitters_url_is_not_authorable():
    _scene, (emitter,) = _loaded({'kind': 'fire', 'externalURL': ['x.wrl']})
    assert list(emitter.externalURL) == []
