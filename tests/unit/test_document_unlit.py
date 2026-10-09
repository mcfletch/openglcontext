"""An appearance with no material, in a document and in code.

X3D (19775-1, 17.2.2.4): where an Appearance's material is NULL the shape is
unlit, its colour the texture's (white without one). A scene built in code
keeps the engine's lit neutral grey for an appearance with no material.
"""
import pytest

from OpenGLContext.scenegraph.physicalmaterial import pbr_material
from OpenGLContext.passes.pbrpass import _material_factors

DOCUMENT = (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/><Shape>"
            b"<Appearance><PixelTexture image='1 1 3 0x00FF00'/></Appearance>"
            b"<IndexedFaceSet coordIndex='0 1 2 3'>"
            b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>"
            b"</Shape></Scene></X3D>")


def appearance_of(scene):
    return scene.children[1].appearance


def test_in_a_document_it_is_unlit():
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    factors = _material_factors(pbr_material(appearance_of(Loader.loads(DOCUMENT, 'a.x3d'))))
    assert factors['unlit'] and tuple(factors['base_color']) == (1.0, 1.0, 1.0)


def test_in_code_it_is_lit():
    from OpenGLContext.scenegraph.basenodes import Appearance  # noqa: PLC0415 kept with its use
    assert not _material_factors(pbr_material(Appearance()))['unlit']


def test_drawn_as_its_texture(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(DOCUMENT, 'a.x3d'), size=(32, 32)) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert tuple(centre) == pytest.approx((0, 255, 0), abs=3)


def test_the_packed_block_follows_the_appearance_into_a_document():
    """Where the appearance belongs is an input of its block"""
    from vrml import protofunctions  # noqa: PLC0415 kept with its use
    from OpenGLContext.passes.pbrpass import pack_material_block  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.basenodes import Appearance  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.scenegraph import X3DScene  # noqa: PLC0415 kept with its use
    appearance = Appearance()
    view = pbr_material(appearance)
    unlit_word = 28
    assert pack_material_block(view).view('int32')[unlit_word] == 0
    document = X3DScene()                   # a node holds its root weakly
    protofunctions.root(appearance, document)
    assert pack_material_block(view).view('int32')[unlit_word] == 1


BARE = (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/><Shape>"
        b"<IndexedFaceSet coordIndex='0 1 2 3'>"
        b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>"
        b"</Shape></Scene></X3D>")


def test_a_shape_with_no_appearance_in_a_document_is_unlit_white(gl_context):
    """X3D: a Shape with no Appearance is drawn as an unlit white"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(BARE, 'a.x3d'), size=(32, 32)) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert tuple(centre) == pytest.approx((255, 255, 255), abs=3)


class StubProbe:
    def __init__(self, studio):
        self.studio = studio


@pytest.mark.parametrize('mode, probe, document, expected', [
    ('analytic', None, True, 'off'),
    ('full', StubProbe(studio=True), True, 'off'),
    ('full', StubProbe(studio=False), True, 'full'),
    ('analytic', None, False, 'analytic'),
    ('full', StubProbe(studio=True), False, 'full'),
    ('off', None, True, 'off'),
])
def test_a_document_has_no_studio_environment(mode, probe, document, expected):
    """X3D lights a document by its lights alone; an environment it supplies is kept"""
    from OpenGLContext.passes import ibl  # noqa: PLC0415 kept with its use
    assert ibl.scene_mode(mode, probe, document) == expected


DARK = (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/>"
        b"<NavigationInfo headlight='false'/><Shape><Appearance>"
        b"<Material diffuseColor='1 1 1'/></Appearance><IndexedFaceSet coordIndex='0 1 2 3'>"
        b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>"
        b"</Shape></Scene></X3D>")


def test_a_document_with_no_light_is_dark(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(DARK, 'a.x3d'), size=(32, 32)) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert max(centre) < 12, centre


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_an_unlit_material_is_its_emissive_colour(gl_context, renderer):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Viewpoint position="0 0 3"/><Shape>'
                         b'<Appearance><UnlitMaterial emissiveColor="1 0.5 0"/></Appearance>'
                         b'<Box size="2 2 0.1"/></Shape></Scene></X3D>', 'scene.x3d')
    with scene_context(scene, size=(32, 32), renderer=renderer) as context:
        drawn_image(context)
        red, green, blue = drawn_image(context).astype(int)[16, 16]
    assert red > 245 and 110 < green < 200 and blue < 10


COLOURED = (b"<IndexedFaceSet coordIndex='0 1 2 3' colorPerVertex='false'>"
            b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/>"
            b"<Color color='0.2 0.5 0.3'/></IndexedFaceSet>")
PLAIN = (b"<IndexedFaceSet coordIndex='0 1 2 3'>"
         b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>")


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
@pytest.mark.parametrize('shape', [
    b"<Shape>" + COLOURED + b"</Shape>",
    b"<Shape><Appearance/>" + COLOURED + b"</Shape>",
    b"<Shape><Appearance><UnlitMaterial/></Appearance>" + COLOURED + b"</Shape>",
    b"<Shape><Appearance><UnlitMaterial emissiveColor='0.2 0.5 0.3'/></Appearance>"
    + PLAIN + b"</Shape>",
])
def test_unlit_colours_are_drawn_as_given(gl_context, renderer, shape):
    """X3D's unlit colours are display values, as X_ITE draws them: 0.2 is 51"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
                         + shape + b"</Scene></X3D>", 'a.x3d')
    with scene_context(scene, size=(32, 32), renderer=renderer) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert tuple(centre) == pytest.approx((51, 128, 77), abs=3)


def test_an_unlit_material_built_in_code_is_linear():
    """glTF's KHR_materials_unlit loads as an UnlitMaterial outside a document:
    its colour is linear light"""
    from OpenGLContext.passes.pbrpass import DISPLAYED_BIT, pack_material_block  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial  # noqa: PLC0415 kept with its use
    flags = int(pack_material_block(UnlitMaterial()).view('int32')[29])
    assert not flags & DISPLAYED_BIT


def test_instanced_shapes_with_no_appearance_are_unlit(gl_context):
    """One Shape used twice is drawn as one instanced batch, unlit as given
    (Vrml2Sourcebook Siggraph98Course/Log's flames)"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    square = (b"<IndexedFaceSet coordIndex='0 1 2 3' colorPerVertex='false'>"
              b"<Coordinate point='-1 -1 0 1 -1 0 1 1 0 -1 1 0'/>"
              b"<Color color='0.2 0.5 0.3'/></IndexedFaceSet>")
    uses = b"".join(b"<Transform translation='%d 0 0'><Shape USE='S'/></Transform>" % x
                    for x in (-4, -2, 2, 4))
    scene = Loader.loads(
        b"<X3D version='3.3'><Scene><Viewpoint position='0 0 12'/>"
        b"<Shape DEF='S'>" + square + b"</Shape>" + uses + b"</Scene></X3D>", 'a.x3d')
    with scene_context(scene, size=(96, 32), instancing=True) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    for column in (35, 42, 48, 54, 61):
        assert tuple(image[16, column]) == pytest.approx((51, 128, 77), abs=3), column
