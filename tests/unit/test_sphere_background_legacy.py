"""In-process GL test: the fixed-function gradient sphere fills the frame.

The compatibility profile's Background is a sphere of radius one about the eye,
drawn with the camera's projection. A camera's near plane is its own business
-- an orbiting editor camera puts it at a share of its distance, well beyond
one unit -- and the sky is drawn whatever it is.
"""
import math

import numpy as np
import pytest

from vrml import cache
from OpenGL import GL

from OpenGLContext.scenegraph.background import Background

SKY = (0.2, 0.4, 0.8)
SIZE = 64


@pytest.fixture
def gl_context(gl_window):
    return gl_window('sphere-bg-legacy', size=(SIZE, SIZE), profile='compatibility')


class _Mode:
    """What the legacy ``Render`` reads of a rendering pass."""

    passCount = 0

    def __init__(self):
        self.cache = cache.Cache()
        self.matrix = np.identity(4, dtype='f')


def _frame(near):
    GL.glViewport(0, 0, SIZE, SIZE)
    GL.glClearColor(0, 0, 0, 1)
    GL.glMatrixMode(GL.GL_PROJECTION)
    GL.glLoadIdentity()
    f = 1.0 / math.tan(math.radians(60) / 2.0)
    far = near * 1000.0
    projection = np.zeros((4, 4), 'f')
    projection[0, 0] = projection[1, 1] = f
    projection[2, 2] = (far + near) / (near - far)
    projection[2, 3] = -1.0
    projection[3, 2] = 2 * far * near / (near - far)
    GL.glLoadMatrixf(projection)
    GL.glMatrixMode(GL.GL_MODELVIEW)
    GL.glLoadIdentity()
    background = Background(skyColor=[SKY])
    background.bound = 1
    background.Render(mode=_Mode(), clear=True)
    raw = GL.glReadPixels(0, 0, SIZE, SIZE, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3)


def _covered(image):
    sky = np.array(SKY) * 255
    return (np.abs(image.astype(int) - sky).max(axis=-1) <= 3).mean()


@pytest.mark.usefixtures('gl_context')
def test_a_near_plane_inside_the_sphere_sees_the_sky_everywhere():
    assert _covered(_frame(0.1)) == pytest.approx(1.0)


@pytest.mark.usefixtures('gl_context')
def test_a_near_plane_beyond_the_sphere_sees_it_too():
    """An orbit camera fifty units out puts its near plane at one."""
    assert _covered(_frame(5.0)) == pytest.approx(1.0)


@pytest.mark.usefixtures('gl_context')
def test_the_depth_range_is_left_clipping_afterwards():
    _frame(5.0)
    assert not GL.glIsEnabled(GL.GL_DEPTH_CLAMP)
