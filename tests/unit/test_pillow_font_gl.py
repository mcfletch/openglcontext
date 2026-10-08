"""Tests for pillowfont, which draws Text nodes from an atlas of lines Pillow drew."""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.text import pillowfont
from OpenGLContext.testing.scenes import drawn_image, scene_context


def text_shape(strings, colour=(1.0, 0.0, 0.0), **style):
    return basenodes.Shape(
        geometry=basenodes.Text(string=list(strings), fontStyle=basenodes.FontStyle(
            justify=['MIDDLE', 'MIDDLE'], **style)),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(0, 0, 0), emissiveColor=colour)))


def drawn(*shapes, size=(160, 80)):
    scene = [basenodes.Viewpoint(position=(0, 0, 6))] + list(shapes)
    with scene_context(scene, size=size) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
        return image, len(pillowfont.text_atlas().textures)


def test_the_text_is_its_materials_colour_with_soft_edges(gl_context):
    image, _pages = drawn(text_shape(['Hello']))
    red = image[:, :, 0]
    assert red.max() > 200 and image[:, :, 1].max() < 40
    assert ((red > 30) & (red < 200)).sum() > 20, 'edges are blended'


def test_a_texts_lines_are_one_draw(gl_context, monkeypatch):
    draws = []
    real = pillowfont.PillowTextFont._draw

    def counting(mode, drawn_lines):
        draws.append(drawn_lines.count)
        return real(mode, drawn_lines)

    monkeypatch.setattr(pillowfont.PillowTextFont, '_draw', staticmethod(counting))
    drawn(text_shape(['one', 'two', 'three']))
    assert draws and all(count == 18 for count in draws)


def test_many_texts_share_one_page(gl_context):
    shapes = [basenodes.Transform(translation=(0, 0.6 * index - 1.5, 0),
                                  children=[text_shape(['line %d' % index], size=0.4)])
              for index in range(6)]
    _image, pages = drawn(*shapes)
    assert pages == 1


def test_a_text_shape_is_blended():
    shape = text_shape(['x'])
    assert getattr(shape.geometry, 'softEdges', False)


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_both_renderers_draw_it(gl_context, renderer):
    scene = [basenodes.Viewpoint(position=(0, 0, 6)), text_shape(['Hello'])]
    with scene_context(scene, size=(160, 80), renderer=renderer) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert np.count_nonzero(image[:, :, 0] > 200) > 50


def test_the_compatibility_profile_draws_it():
    scene = [basenodes.Viewpoint(position=(0, 0, 6)), text_shape(['Hello'])]
    with scene_context(scene, size=(160, 80),
                       environment={'OPENGLCONTEXT_PROFILE': 'compatibility'}) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert np.count_nonzero(image[:, :, 0] > 200) > 50
    red = image[:, :, 0]
    assert ((red > 30) & (red < 200)).sum() > 20, 'edges are blended'
