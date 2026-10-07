"""Texture coordinates for a face set with no texCoord.

X3D (19775-1, Geometry3D, IndexedFaceSet; Rendering, X3DComposedGeometryNode):
s runs from 0 to 1 along the largest dimension of the coordinates' bounding
box, t along the second largest from 0 to that dimension's size over the
largest's. Ties go to X, then Y, then Z.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.composedgeometry import default_texcoords


def test_s_along_the_largest_and_t_along_the_next():
    points = np.array([(-1.5, 0, 0), (1.5, 0, 0), (1.5, 3, 0), (-1.5, 3, 0)], 'f')
    assert default_texcoords(points) == pytest.approx(
        np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'))


def test_t_is_scaled_by_the_largest():
    points = np.array([(0, 0, 0), (0, 0, 4), (0, 2, 4)], 'f')
    assert default_texcoords(points) == pytest.approx(
        np.array([(0, 0), (1, 0), (1, 0.5)], 'f'))


def test_ties_go_to_x_then_y_then_z():
    points = np.array([(0, 0, 0), (1, 1, 1)], 'f')
    assert default_texcoords(points) == pytest.approx(np.array([(0, 0), (1, 1)], 'f'))
    points = np.array([(0, 0, 0), (0, 1, 1)], 'f')
    assert default_texcoords(points)[1] == pytest.approx((1, 1))


def test_the_box_may_be_the_whole_coordinate_set():
    points = np.array([(1, 0, 0), (2, 0, 0)], 'f')
    every = np.array([(0, 0, 0), (2, 1, 0)], 'f')
    assert default_texcoords(points, every) == pytest.approx(np.array([(0.5, 0), (1, 0)], 'f'))


def test_a_single_point():
    assert default_texcoords(np.array([(3, 3, 3)], 'f')) == pytest.approx(np.zeros((1, 2)))


def drawn(geometry):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(
        b'<X3D version="3.3"><Scene><Viewpoint position="0 0 0"/><Shape><Appearance>'
        b"<PixelTexture image='4 1 3 0xFF0000 0xFF0000 0x00FF00 0x00FF00'/></Appearance>"
        + geometry
        + b'</Shape></Scene></X3D>', 'scene.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


QUAD = b"<Coordinate point='-1 -1 -3 1 -1 -3 1 1 -3 -1 1 -3'/>"


@pytest.mark.parametrize('geometry', [
    b"<IndexedFaceSet coordIndex='0 1 2 3' solid='false'>" + QUAD + b'</IndexedFaceSet>',
    b"<IndexedTriangleSet index='0 1 2 0 2 3' solid='false'>" + QUAD + b'</IndexedTriangleSet>',
], ids=['IndexedFaceSet', 'IndexedTriangleSet'])
def test_a_face_set_with_no_texcoord_spans_its_image(gl_context, geometry):
    image = drawn(geometry)
    left, right = image[16, 8], image[16, 24]
    assert left[0] > left[1] + 100, left
    assert right[1] > right[0] + 100, right
