"""Primitive and texture quality (X_ITE's PrimitiveQuality and TextureQuality)"""
import numpy as np
import pytest

from OpenGLContext import contextdefinition, renderoptions
from OpenGLContext.passes import quality
from OpenGLContext.scenegraph import sampler


@pytest.fixture(autouse=True)
def automatic():
    quality.use('auto', 'auto')
    yield
    quality.use('auto', 'auto')


def document_node(text):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    scene = Loader.loads(b"<X3D version='4.0'><Scene><Shape DEF='S'>" + text
                         + b"</Shape></Scene></X3D>", 'a.x3d')
    return scene.getDEF('S')


def rings_and_sides(coords):
    """(rings, sides) of a sphere's interleaved arrays, from its distinct heights and the equator"""
    points = np.asarray(coords, 'f').reshape(-1, 8)
    heights = np.unique(np.round(points[:, 1], 5))
    equator = points[np.abs(points[:, 1]) < 1e-4] if len(heights) % 2 else None
    return len(heights) - 1, (None if equator is None else len(equator) - 1)


def test_a_documents_sphere_is_x_ites_medium():
    sphere = document_node(b"<Sphere/>").geometry
    coords, _indices = sphere.compileArrays(0)
    assert rings_and_sides(coords)[0] == 14
    assert len(coords) == 15 * 33


def test_a_sphere_built_in_code_keeps_the_engines_tessellation():
    from OpenGLContext.scenegraph.basenodes import Sphere  # noqa: PLC0415 kept with its use
    coords, _indices = Sphere().compileArrays(0)
    assert len(coords) == 13 * 25


@pytest.mark.parametrize('choice, rings, points', [
    ('low', 8, 9 * 21), ('medium', 14, 15 * 33), ('high', 30, 31 * 65)])
def test_the_chosen_quality_tessellates_every_sphere(choice, rings, points):
    from OpenGLContext.scenegraph.basenodes import Sphere  # noqa: PLC0415 kept with its use
    quality.use(choice, 'auto')
    coords, _indices = Sphere().compileArrays(0)
    assert len(coords) == points
    assert rings_and_sides(coords)[0] == rings


@pytest.mark.parametrize('text', [b"<Cylinder/>", b"<Cone/>"])
def test_a_documents_cylinder_and_cone_have_twenty_sides(text):
    geometry = document_node(text).geometry
    coords, _indices = geometry.compileArrays(0)
    points = np.asarray(coords, 'f').reshape(-1, 8)
    around = np.unique(np.round(np.arctan2(points[:, 0], points[:, 2]), 4))
    around = around[np.abs(np.abs(around) - np.pi) > 1e-3]   # one seam angle, two spellings
    assert len(around) == 20 - 1 or len(around) == 20


def test_a_quality_change_is_a_new_mesh():
    sphere = document_node(b"<Sphere/>").geometry
    medium = sphere.mesh()
    medium_key = sphere.instanceContentKey()
    quality.use('high', 'auto')
    assert sphere.mesh() is not medium
    assert sphere.instanceContentKey() != medium_key


def test_a_documents_texture_is_filtered_as_x_ites_medium():
    texture = document_node(b"<Appearance><ImageTexture/></Appearance><Box/>").appearance.texture
    found = sampler.sampler_of(texture, (64, 64))
    assert (found['minification'], found['magnification']) == (
        'AVG_PIXEL_NEAREST_MIPMAP', 'AVG_PIXEL')


def test_a_texture_built_in_code_keeps_trilinear():
    from OpenGLContext.scenegraph.basenodes import ImageTexture  # noqa: PLC0415 kept with its use
    found = sampler.sampler_of(ImageTexture(), (64, 64))
    assert found['minification'] == 'AVG_PIXEL_AVG_MIPMAP'


@pytest.mark.parametrize('minification, magnification, expected', [
    (b'DEFAULT', b'DEFAULT', ('NEAREST_PIXEL_NEAREST_MIPMAP', 'NEAREST_PIXEL')),
    (b'NICEST', b'NICEST', ('AVG_PIXEL_AVG_MIPMAP', 'AVG_PIXEL')),
    (b'AVG_PIXEL', b'NEAREST_PIXEL', ('AVG_PIXEL', 'NEAREST_PIXEL')),
])
def test_texture_properties_at_low_quality(minification, magnification, expected):
    quality.use('auto', 'low')
    texture = document_node(
        b"<Appearance><ImageTexture><TextureProperties minificationFilter='%s'"
        b" magnificationFilter='%s'/></ImageTexture></Appearance><Box/>"
        % (minification, magnification)).appearance.texture
    found = sampler.sampler_of(texture, (64, 64))
    assert (found['minification'], found['magnification']) == expected


def test_an_unknown_quality_is_refused():
    with pytest.raises(ValueError):
        quality.use('ultra', 'auto')


def test_the_environment_is_the_default(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_PRIMITIVE_QUALITY', 'high')
    monkeypatch.setenv('OPENGLCONTEXT_TEXTURE_QUALITY', 'LOW')
    renderoptions.reset_env_cache()
    assert quality.chosen(contextdefinition.ContextDefinition()) == ('high', 'low')
    for name in ('OPENGLCONTEXT_PRIMITIVE_QUALITY', 'OPENGLCONTEXT_TEXTURE_QUALITY'):
        assert name in renderoptions.ENVIRONMENT


def test_a_settings_screen_offers_them():
    hints = contextdefinition.ContextDefinition.UI_HINTS
    for name in ('primitiveQuality', 'textureQuality'):
        assert hints[name]['options'] == quality.CHOICES
        assert name in contextdefinition.ContextDefinition.RENDERING_FIELDS


def test_the_pass_draws_with_the_definitions_choices(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b"<X3D version='4.0'><Scene><Shape><Sphere/></Shape></Scene></X3D>",
                         'a.x3d')
    with scene_context(scene, size=(16, 16), primitiveQuality='low',
                       textureQuality='high') as context:
        drawn_image(context)
    assert quality.primitive_quality(True) == 'low'
    assert quality.texture_quality(True) == 'high'
