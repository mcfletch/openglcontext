"""A background's shader program belongs to the context that compiled it.

A GL program is a *name*, and it means something only in the context that
issued it. An application with two contexts is ordinary here -- the embedding
demos put a view in each of two windows, and ``Context.allContexts`` is a list
-- so a program cached where the second context can reach it is a
``glUseProgram`` on a name that context has never heard of: an invalid-value
error, and a background that does not paint.

:mod:`OpenGLContext.contextresources` is what the engine keys GL objects with,
and what it announces a context's death through.

The gradient sphere (``spherebackground``) and the HDR panorama
(``hdrbackground``) both draw through a program of their own, so both are held
to this.
"""
import math

import numpy as np
import pytest

from vrml import cache

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.hdrbackground import HDRBackground

SIZE = 64


def _perspective(fovy, aspect, near, far):
    f = 1.0 / math.tan(fovy / 2.0)
    P = np.zeros((4, 4), dtype='f')
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = -1.0
    P[3, 2] = (2 * far * near) / (near - far)
    return P


class _Mode:
    passCount = 0
    context = None
    _bloom_active = False

    def __init__(self):
        self.cache = cache.Cache()
        self.matrix = np.identity(4, dtype='f')
        self.projection = _perspective(math.radians(60), 1.0, 1.0, 500.0)


def _panorama(h=32, w=64):
    env = np.zeros((h, w, 3), np.float32)
    env[:h // 2] = (2.0, 0.3, 0.3)
    env[h // 2:] = (0.2, 0.2, 2.0)
    return env


def _gradient_sphere():
    background = Background(skyColor=[(1, 0, 0), (0, 0, 1)],
                            skyAngle=[math.pi / 2.0])
    background.bound = 1
    return background


def _panorama_background():
    background = HDRBackground(image=_panorama())
    background.bound = 1
    return background


def _draw(background):
    """Draw into whichever context is current, and read the frame back."""
    from OpenGL.GL import (
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_FRAMEBUFFER, GL_RGB,
        GL_UNSIGNED_BYTE, glBindFramebuffer, glClear, glClearColor,
        glReadPixels, glViewport,
    )
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glViewport(0, 0, SIZE, SIZE)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    background.RenderShader(mode=_Mode(), clear=False)
    raw = glReadPixels(0, 0, SIZE, SIZE, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3)


@pytest.mark.parametrize('build', [_gradient_sphere, _panorama_background],
                         ids=['gradient-sphere', 'hdr-panorama'])
class TestASecondContextPaints:
    def test_it_draws_in_both(self, gl_window, build):
        """Two contexts, a background in each, and both frames have colour in them."""
        gl_window('first', size=(SIZE, SIZE))
        first = _draw(build()).max()
        assert first > 20, 'nothing drawn in the first context'

        gl_window('second', size=(SIZE, SIZE))
        second = _draw(build()).max()
        assert second > 20, 'nothing drawn in the second context'

    def test_the_same_node_draws_in_both(self, gl_window, build):
        """One node moved between contexts, as a scenegraph shared by two views."""
        background = build()
        gl_window('first', size=(SIZE, SIZE))
        assert _draw(background).max() > 20, 'nothing drawn in the first context'

        gl_window('second', size=(SIZE, SIZE))
        assert _draw(background).max() > 20, 'nothing drawn in the second context'
