"""Tests for how a 2D texture is sampled: its filters from TextureProperties,
and a document's small images drawn pixel for pixel"""
import pytest
from OpenGL import GL
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes, sampler
from OpenGLContext.testing.scenes import drawn_image, scene_context

CHECKER = '2 2 1 0xff 0x00 0x00 0xff'


def document_texture(texture):
    scene = Loader.loads(('<X3D version="4.0"><Scene><Viewpoint position="0 0 3"/><Shape>'
                          '<Appearance>%s</Appearance><Box size="2 2 0.1"/></Shape>'
                          '</Scene></X3D>' % texture).encode(), 'scene.x3d')
    return scene, scene.children[1].appearance.texture


@pytest.mark.parametrize('size, expected', [((2, 2), 'NEAREST_PIXEL'), ((15, 4), 'NEAREST_PIXEL'),
                                            ((16, 16), 'DEFAULT'), ((256, 2), 'DEFAULT')])
def test_a_documents_small_image_is_sampled_by_its_nearest_pixel(size, expected):
    _scene, texture = document_texture('<PixelTexture image="%s"/>' % CHECKER)
    found = sampler.sampler_of(texture, size)
    assert found['minification'] == found['magnification'] == expected


def test_texture_properties_choose_for_a_small_image():
    _scene, texture = document_texture(
        '<PixelTexture image="%s"><TextureProperties magnificationFilter="AVG_PIXEL" '
        'minificationFilter="AVG_PIXEL"/></PixelTexture>' % CHECKER)
    assert sampler.sampler_of(texture, (2, 2))['magnification'] == 'AVG_PIXEL'


def test_a_small_image_built_in_code_takes_the_engines_filters():
    texture = basenodes.PixelTexture(image=[2, 2, 1, 0xff, 0, 0, 0xff])
    assert sampler.sampler_of(texture, (2, 2))['magnification'] == 'DEFAULT'


def test_a_pixel_texture_answers_its_size():
    assert basenodes.PixelTexture(image=[3, 2, 1, 0, 0, 0, 0, 0, 0]).imageSize() == (3, 2)
    assert basenodes.PixelTexture().imageSize() is None


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_documents_pixel_texture_is_drawn_crisp(gl_context, renderer):
    """Magnified, a 2x2 checker is four flat squares: nothing between black and white"""
    scene, texture = document_texture(
        '<UnlitMaterial emissiveColor="1 1 1"/><PixelTexture image="%s"/>' % CHECKER)
    with scene_context(scene, size=(64, 64), renderer=renderer) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)[16:48, 16:48, 0]
    bright = image.max()
    assert bright > 150
    between = ((image > 0.15 * bright) & (image < 0.85 * bright)).mean()
    assert between < 0.05, between
