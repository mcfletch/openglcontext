"""A cube map's faces are square and one size, whatever size the images are.

GL refuses a cube map face that is not square, or not the size of the others;
backgrounds are often published as 300x200 photographs. Each face is
resampled to a square as wide as the largest side among them.
"""
import numpy as np
import pytest
from OpenGL import GL
from PIL import Image

from OpenGLContext.texture import CubeTexture

FACES = ('-x', '+x', '-y', '+y', '-z', '+z')


def face_size(tex, face):
    GL.glBindTexture(GL.GL_TEXTURE_CUBE_MAP, tex.texture)
    try:
        target = CubeTexture.CUBE_NAME_MAP[face]
        return (int(GL.glGetTexLevelParameteriv(target, 0, GL.GL_TEXTURE_WIDTH)),
                int(GL.glGetTexLevelParameteriv(target, 0, GL.GL_TEXTURE_HEIGHT)))
    finally:
        GL.glBindTexture(GL.GL_TEXTURE_CUBE_MAP, 0)


def test_photographs_of_several_shapes(gl_context):
    images = {face: Image.new('RGB', (300, 200) if index % 2 else (64, 64), (index * 40, 0, 0))
              for index, face in enumerate(FACES)}
    tex = CubeTexture()
    tex.fromPIL(images)
    assert {face: face_size(tex, face) for face in FACES} == {face: (300, 300) for face in FACES}


def test_square_faces_are_kept(gl_context):
    tex = CubeTexture()
    tex.fromPIL({face: Image.new('RGB', (32, 32)) for face in FACES})
    assert face_size(tex, '+z') == (32, 32)


def test_array_faces_of_two_sizes_are_refused():
    faces = {face: np.zeros((8, 8, 3), np.uint8) for face in FACES}
    faces['+z'] = np.zeros((4, 4, 3), np.uint8)
    with pytest.raises(ValueError):
        CubeTexture().fromPIL(faces)
