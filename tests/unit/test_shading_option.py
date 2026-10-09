"""The shading option: points, wireframe, flat, Gouraud and Phong (X_ITE's Shading)

Gouraud, as X3D 19775-1 17.2.2.7 recommends and X_ITE draws it: the lighting
equation without the textures, times the main texture. Phong: the texture
multiplies the diffuse colour before the lighting (17.2.2.5).
"""
import pytest

from OpenGLContext import contextdefinition, renderoptions
from OpenGLContext.passes import shading


@pytest.mark.parametrize('chosen, document, expected', [
    ('auto', True, 'gouraud'),
    ('auto', False, 'phong'),
    ('FLAT', True, 'flat'),
    ('wireframe', False, 'wireframe'),
])
def test_the_shading_a_choice_draws_with(chosen, document, expected):
    assert shading.resolve(chosen, document) == expected


def test_an_unknown_shading_is_refused():
    with pytest.raises(ValueError):
        shading.resolve('toon', False)


def test_x_ites_pointset_spelling_is_points():
    assert shading.resolve('POINTSET', False) == 'point'


def test_points_and_wireframe_are_polygon_modes():
    from OpenGL.GL import GL_LINE, GL_POINT  # noqa: PLC0415 kept with its use
    assert shading.polygon_mode('point') == GL_POINT
    assert shading.polygon_mode('wireframe') == GL_LINE
    assert shading.polygon_mode('gouraud') is None


def test_the_environment_is_the_default(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_SHADING', 'flat')
    renderoptions.reset_env_cache()
    assert shading.chosen(contextdefinition.ContextDefinition()) == 'flat'
    assert 'OPENGLCONTEXT_SHADING' in renderoptions.ENVIRONMENT


def test_a_settings_screen_offers_it():
    hints = contextdefinition.ContextDefinition.UI_HINTS
    assert hints['shading']['options'] == shading.CHOICES
    assert 'shading' in contextdefinition.ContextDefinition.RENDERING_FIELDS


QUAD = (b"<IndexedFaceSet coordIndex='0 1 2 3' texCoordIndex='0 1 2 3'%s>"
        b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/>"
        b"<TextureCoordinate point='0 0 1 0 1 1 0 1'/>%s</IndexedFaceSet>")


def document(appearance, normals=b''):
    geometry = QUAD % ((b" normalPerVertex='true'", normals) if normals else (b'', b''))
    return (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/><Shape><Appearance>"
            + appearance + b"</Appearance>" + geometry + b"</Shape></Scene></X3D>")


def centre(text, at=(16, 16), **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(text, 'a.x3d'), size=(32, 32), **definition) as context:
        drawn_image(context)
        image = drawn_image(context)
        return tuple(image[at].astype(int)), image


GREY = b"<PixelTexture image='1 1 3 0x808080'/>"
EMISSIVE = b"<Material diffuseColor='0 0 0' specularColor='0 0 0' emissiveColor='0.5 0.5 0.5'/>"
SPECULAR = b"<Material diffuseColor='0 0 0' specularColor='0.5 0.5 0.5'/>"


@pytest.mark.parametrize('appearance, definition, expected', [
    # Gouraud, a document's default: the texture multiplies the emissive colour too
    (EMISSIVE + GREY, {}, 64),
    (EMISSIVE + GREY, {'shading': 'phong'}, 128),
    # ...and the specular highlight
    (SPECULAR + GREY, {'shading': 'gouraud'}, 64),
    (SPECULAR + GREY, {'shading': 'phong'}, 128),
])
def test_where_the_texture_applies(gl_context, appearance, definition, expected):
    found, _image = centre(document(appearance), **definition)
    assert found == pytest.approx((expected,) * 3, abs=3)


def test_flat_shading_uses_the_faces_own_normal(gl_context):
    tilted = b"<Normal vector='0.7071 0 0.7071 0.7071 0 0.7071 0.7071 0 0.7071 0.7071 0 0.7071'/>"
    lit = b"<Material diffuseColor='1 1 1' specularColor='0 0 0'/>"
    smooth, _image = centre(document(lit, tilted), shading='phong')
    flat, _image = centre(document(lit, tilted), shading='flat')
    assert smooth == pytest.approx((180,) * 3, abs=3)
    assert flat == pytest.approx((255,) * 3, abs=3)


@pytest.mark.parametrize('choice', ['wireframe', 'point'])
def test_points_and_wireframe_leave_the_face_undrawn(gl_context, choice):
    lit = b"<Material diffuseColor='1 1 1'/>"
    found, _image = centre(document(lit), shading=choice)
    assert found == (0, 0, 0)
    whole, _image = centre(document(lit))
    assert whole != (0, 0, 0)


def test_wireframe_draws_the_edges(gl_context):
    near = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/><Shape><Appearance>"
            b"<Material emissiveColor='1 1 1'/></Appearance>"
            b"<IndexedFaceSet coordIndex='0 1 2 -1'>"
            b"<Coordinate point='-0.3 -0.3 -1 0.3 -0.3 -1 0 0.3 -1'/></IndexedFaceSet>"
            b"</Shape></Scene></X3D>")
    _found, image = centre(near, shading='wireframe')
    assert (image[..., 0] > 200).sum() > 10
