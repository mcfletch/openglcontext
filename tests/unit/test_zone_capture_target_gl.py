"""A zone's capture leaves the caller's GL state as it found it."""

import numpy as np
from OpenGL.GL import (
    GL_COLOR_CLEAR_VALUE,
    GL_FRAMEBUFFER_BINDING,
    GL_VIEWPORT,
    glClearColor,
    glGetFloatv,
    glGetIntegerv,
)

from OpenGLContext.passes.zoneprobes import CaptureTarget


def test_a_capture_leaves_the_clear_colour_it_found(gl_context):
    glClearColor(0.25, 0.5, 0.75, 0.5)
    viewport = [int(value) for value in glGetIntegerv(GL_VIEWPORT)]
    framebuffer = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
    target = CaptureTarget(16)
    try:
        target.begin()
        for face in range(6):
            target.face(face)
        target.end(whole=True)
        assert np.allclose(glGetFloatv(GL_COLOR_CLEAR_VALUE),
                           (0.25, 0.5, 0.75, 0.5))
        assert [int(value) for value in glGetIntegerv(GL_VIEWPORT)] == viewport
        assert int(glGetIntegerv(GL_FRAMEBUFFER_BINDING)) == framebuffer
    finally:
        target.release()
