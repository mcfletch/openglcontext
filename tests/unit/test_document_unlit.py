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
