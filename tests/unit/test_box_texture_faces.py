"""A Box's texture coordinates follow X3D's rule for each face.

X3D (19775-1, Geometry3D, Box): each side face shows the image upright seen
from outside with +Y up; the top seen from above with -Z as the view up; the
bottom seen from below with +Z as the view up. So on each face u runs along
the viewer's right and v along the viewer's up, from 0 to 1.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.box import yieldVertices

#: normal: (the viewer's right, the viewer's up), looking at the face from outside
FACES = {
    (0, 0, 1): ((1, 0, 0), (0, 1, 0)),
    (0, 0, -1): ((-1, 0, 0), (0, 1, 0)),
    (1, 0, 0): ((0, 0, -1), (0, 1, 0)),
    (-1, 0, 0): ((0, 0, 1), (0, 1, 0)),
    (0, 1, 0): ((1, 0, 0), (0, 0, -1)),
    (0, -1, 0): ((1, 0, 0), (0, 0, 1)),
}


@pytest.mark.parametrize('normal', sorted(FACES))
def test_each_face_shows_the_image_as_x3d_says(normal):
    size = np.array([2.0, 4.0, 6.0])
    right, up = (np.array(axis, float) for axis in FACES[normal])
    vertices = [np.array(v, float) for v in yieldVertices(size)]
    face = [v for v in vertices if tuple(v[2:5]) == normal]
    assert len(face) == 6
    for vertex in face:
        position = vertex[5:8]
        expected = (position @ right / (abs(right) @ size) + 0.5,
                    position @ up / (abs(up) @ size) + 0.5)
        assert tuple(vertex[0:2]) == pytest.approx(expected), (normal, position)
