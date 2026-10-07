"""An IndexedFaceSet's Color is drawn in both shader passes.

X3D (19775-1, Lighting, Lighting model): the colours of a ``Color`` or
``ColorRGBA`` node replace the ``Material``'s ``diffuseColor``.
"""
import pytest

from OpenGLContext.loaders.loader import Loader

SQUARE = (b"<IndexedFaceSet coordIndex='0 1 2 3' colorPerVertex='false'>"
          b"<Coordinate point='-1 -1 0 1 -1 0 1 1 0 -1 1 0'/>%s</IndexedFaceSet>")


def _document(colour):
    return Loader.loads(
        b"<X3D version='3.3'><Scene><Viewpoint position='0 0 3'/>"
        b"<Shape><Appearance><Material diffuseColor='1 1 1'/></Appearance>"
        + SQUARE % (colour,) + b"</Shape></Scene></X3D>", 'scene.x3d')


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
@pytest.mark.parametrize('colour', [b"<Color color='1 0 0'/>",
                                    b"<ColorRGBA color='1 0 0 1'/>"])
def test_the_face_is_its_colour(renderer, colour):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(_document(colour), size=(32, 32), renderer=renderer) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert centre[0] > 120 and centre[1] < 40 and centre[2] < 40, centre


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_used_twice_both_are_their_colour(renderer):
    """Two uses of one Shape are drawn as one instanced draw"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(
        b"<X3D version='3.3'><Scene><Viewpoint position='0 0 6'/>"
        b"<Transform translation='-1.2 0 0'><Shape DEF='S'><Appearance>"
        b"<Material diffuseColor='1 1 1'/></Appearance>"
        + SQUARE % (b"<Color color='1 0 0'/>",) + b"</Shape></Transform>"
        b"<Transform translation='1.2 0 0'><Shape USE='S'/></Transform>"
        b"</Scene></X3D>", 'scene.x3d')
    with scene_context(scene, size=(64, 32), renderer=renderer, instancing=True) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    for pixel in (image[16, 24], image[16, 40]):
        assert pixel[0] > 120 and pixel[1] < 40 and pixel[2] < 40, pixel


def test_the_instanced_mesh_follows_its_inputs(gl_context, check_memo_inputs):
    from types import SimpleNamespace  # noqa: PLC0415 kept with its use
    from vrml import cache  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.basenodes import (  # noqa: PLC0415 kept with its use
        Color, Coordinate, IndexedFaceSet, Normal, TextureCoordinate)
    face_set = IndexedFaceSet(
        coord=Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0)]), coordIndex=[0, 1, 2],
        color=Color(color=[(1, 0, 0)]), colorPerVertex=False)
    mode = SimpleNamespace(cache=cache.CACHE)
    check_memo_inputs(
        lambda: face_set.instanceGPU(mode),
        [('point', lambda: setattr(face_set.coord, 'point',
                                   [(-2, -1, 0), (1, -1, 0), (1, 1, 0)])),
         ('color', lambda: setattr(face_set.color, 'color', [(0, 1, 0)])),
         ('normal', lambda: setattr(face_set, 'normal', Normal(vector=[(0, 0, -1)] * 3))),
         ('normal vector', lambda: setattr(face_set.normal, 'vector', [(0, 0, 1)] * 3)),
         ('texCoord', lambda: setattr(face_set, 'texCoord',
                                      TextureCoordinate(point=[(0, 0), (1, 0), (1, 1)]))),
         ('ccw', lambda: setattr(face_set, 'ccw', False))],
        same=lambda a, b: a is b)


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_face_set_without_colours_after_one_with_them(renderer):
    """The uniform outlives the draw that set it: the white square drawn after
    the red one is white"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(
        b"<X3D version='3.3'><Scene><Viewpoint position='0 0 6'/>"
        b"<Transform translation='-1.2 0 0'><Shape><Appearance><Material diffuseColor='1 1 1'/>"
        b"</Appearance>" + SQUARE % (b"<Color color='1 0 0'/>",) + b"</Shape></Transform>"
        b"<Transform translation='1.2 0 0'><Shape><Appearance><Material diffuseColor='1 1 1'/>"
        b"</Appearance>" + SQUARE % (b"",) + b"</Shape></Transform></Scene></X3D>", 'scene.x3d')
    with scene_context(scene, size=(64, 32), renderer=renderer) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    left, right = image[16, 24], image[16, 40]
    assert left[0] > 120 and left[1] < 40, left
    assert right[1] > 120 and right[2] > 120, right
