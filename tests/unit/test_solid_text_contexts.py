"""Solid TrueType text draws in every GL context it is shown in.

A font is cached for the whole process -- every ``Text`` node asking for the
same face and size gets the same one -- while a GL buffer or vertex array name
means something only in the context that made it.  So the glyph geometry a
solid font uploads is held once per context, and a second window showing the
same text uploads its own rather than binding the first window's names.
"""
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.text.toolsfont import ToolsSolidFont
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

PBR = {'OPENGLCONTEXT_RENDERER': 'pbr'}


@pytest.fixture(autouse=True)
def _core_profile():
    reason = profile_unavailable('core')
    if reason:
        pytest.skip(reason)


def _drawn():
    """What a context draws of one line of text, and the font that drew it"""
    text = basenodes.Text(string=['still'])
    scene = [basenodes.Transform(translation=(-1, 0, 0), children=[
        basenodes.Shape(
            geometry=text,
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=(1, 1, 1))))])]
    with scene_context(scene, environment=PBR) as context:
        context.OnDraw(force=1)
        image = drawn_image(context)
        _provider, font, _lines = context.cache.getData(text)
    return image, font


def test_the_same_text_draws_in_a_second_context():
    first, firstFont = _drawn()
    second, secondFont = _drawn()
    assert isinstance(firstFont, ToolsSolidFont)
    assert secondFont is firstFont, 'the font is shared, which is the case here'
    assert first.max() > 60, 'the text drew nothing in the first context'
    assert second.max() > 60, 'the text drew nothing in the second context'
