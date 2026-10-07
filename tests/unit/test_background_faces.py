"""A Background's six images: each side drawn on its own, the way X3D turns it.

X3D (19775-1, Environmental effects, Background): seen from the origin, a
side face (front -Z, back +Z, left -X, right +X) shows its image upright with
+Y up; the top, looking along +Y with +Z up; the bottom, looking along -Y with
-Z up. A side with no image leaves the sky and ground showing there, and so
does a transparent part of one.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.cubebackground import FACES, face_quad

#: side: (the direction looked along, the view up), from the origin
VIEWS = {
    'front': ((0, 0, -1), (0, 1, 0)),
    'back': ((0, 0, 1), (0, 1, 0)),
    'left': ((-1, 0, 0), (0, 1, 0)),
    'right': ((1, 0, 0), (0, 1, 0)),
    'top': ((0, 1, 0), (0, 0, 1)),
    'bottom': ((0, -1, 0), (0, 0, -1)),
}


def test_the_six_sides():
    assert set(FACES) == set(VIEWS)


@pytest.mark.parametrize('side', sorted(VIEWS))
def test_each_side_shows_its_image_as_x3d_says(side):
    looking, up = (np.array(axis, float) for axis in VIEWS[side])
    right = np.cross(looking, up)
    positions, texcoords = face_quad(side)
    assert len(positions) == len(texcoords) == 4
    for position, (u, v) in zip(positions, texcoords):
        position = np.asarray(position, float)
        assert position @ looking == pytest.approx(1.0), 'on the face looked at'
        assert (u, v) == pytest.approx((position @ right / 2 + 0.5, position @ up / 2 + 0.5))


def drawn(content, size=32):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Viewpoint position="0 0 0"/>'
                         + content + b'</Scene></X3D>', 'scene.x3d')
    with scene_context(scene, size=(size, size)) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


def side(name, image):
    return b'<PixelTexture containerField="%sTexture" image="%s"/>' % (name, image)


def test_one_side_is_drawn_without_the_others(gl_context):
    image = drawn(b'<TextureBackground skyColor="0 0 1">'
                  + side(b'front', b'1 1 3 0x00FF00') + b'</TextureBackground>')
    centre = image[16, 16]
    assert centre[1] > centre[2] + 100, centre


def test_the_front_is_upright(gl_context):
    """Red over green: an SFImage lists its bottom row first"""
    image = drawn(b'<TextureBackground skyColor="0 0 1">'
                  + side(b'front', b'1 2 3 0x00FF00 0xFF0000') + b'</TextureBackground>')
    top, bottom = image[4, 16], image[28, 16]
    assert top[0] > top[1] + 100, top
    assert bottom[1] > bottom[0] + 100, bottom


def test_a_transparent_side_shows_the_sky(gl_context):
    image = drawn(b'<TextureBackground skyColor="0 0 1">'
                  + side(b'front', b'1 1 4 0x00FF0000') + b'</TextureBackground>')
    centre = image[16, 16]
    assert centre[2] > centre[1] + 100, centre


#: GL's cube map faces (OpenGL 4.6 core, table 8.19): side: (major axis, sc, tc),
#: each a function of the direction r, with s = (sc/|ma| + 1)/2, t = (tc/|ma| + 1)/2
#: and t = 0 the image's top row.
GL_FACES = {
    'right': (lambda r: r[0], lambda r: -r[2], lambda r: -r[1]),
    'left': (lambda r: -r[0], lambda r: r[2], lambda r: -r[1]),
    'top': (lambda r: r[1], lambda r: r[0], lambda r: r[2]),
    'bottom': (lambda r: -r[1], lambda r: r[0], lambda r: -r[2]),
    'back': (lambda r: r[2], lambda r: r[0], lambda r: -r[1]),
    'front': (lambda r: -r[2], lambda r: -r[0], lambda r: -r[1]),
}


@pytest.mark.parametrize('side', sorted(GL_FACES))
def test_a_cube_map_layout_samples_as_gl_does(side):
    major, sc, tc = GL_FACES[side]
    positions, texcoords = face_quad(side, 'CUBEMAP')
    for position, (u, v) in zip(positions, texcoords):
        ma = abs(major(position))
        s, t = (sc(position) / ma + 1) / 2, (tc(position) / ma + 1) / 2
        assert (u, 1 - v) == pytest.approx((s, t)), (side, position)


def test_the_engines_cube_background_names_its_layout():
    from OpenGLContext.scenegraph.cubebackground import CubeBackground  # noqa: PLC0415 kept with its use
    assert CubeBackground().faceLayout == 'X3D'
    assert CubeBackground(faceLayout='CUBEMAP').faceLayout == 'CUBEMAP'
