"""The shader's zone distances are the Python ones, for every kind of shape (GL).

``zoneDistance`` in ``_zone_inc.glsl`` is drawn for points spread in and
around each shape -- one point per pixel of a float framebuffer -- and read
back against :func:`OpenGLContext.scenegraph.zones._distance`. The shapes
include the ones whose arithmetic has branches: a capsule with uneven ends,
one whose larger end swallows the other and one of no height, and a tapered
cylinder.
"""
import numpy as np
import pytest
from OpenGL import GL
from OpenGL.GL import shaders

from OpenGLContext.scenegraph import zones
from OpenGLContext.passes.shadersource import _resolve_includes
from OpenGLContext.testing.glcontext import gl_available, hidden_window

#: Sample points per shape.
COUNT = 512

_VERTEX = '''#version 330 core
layout(location = 0) in vec3 aPoint;
flat out vec3 vPoint;
uniform int count;
void main() {
    vPoint = aPoint;
    float x = (float(gl_VertexID) + 0.5) / float(count) * 2.0 - 1.0;
    gl_Position = vec4(x, 0.0, 0.0, 1.0);
}
'''

_FRAGMENT = '''#version 330 core
#include "_zone_inc.glsl"
flat in vec3 vPoint;
out vec4 colour;
void main() {
    colour = vec4(zoneDistance(0, vPoint), 0.0, 0.0, 1.0);
}
'''

#: (kind, params) as a placed shape measures them, and how far round it to sample.
SHAPES = [
    (zones.BOX, (1.5, 0.5, 2.0), 3.0),
    (zones.SPHERE, (1.25,), 2.5),
    (zones.ELLIPSOID, (2.0, 0.5, 1.0), 3.0),
    (zones.CAPSULE, (0.5, 0.5, 2.0), 3.0),
    (zones.CAPSULE, (0.8, 0.3, 1.5), 3.0),        # uneven ends
    (zones.CAPSULE, (2.0, 0.2, 1.0), 3.5),        # the lower sphere swallows the upper
    (zones.CAPSULE, (0.6, 0.6, 0.0), 2.0),        # no height: a sphere
    (zones.CYLINDER, (0.7, 0.7, 2.0), 3.0),
    (zones.CYLINDER, (1.2, 0.4, 2.5), 3.0),       # tapered
]


@pytest.fixture(scope='module')
def program():
    if not gl_available():
        pytest.skip('no GL context can be made here')
    with hidden_window('zone distances', size=(COUNT, 1)):
        linked = shaders.compileProgram(
            shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER),
            shaders.compileShader(_resolve_includes(_FRAGMENT, set()), GL.GL_FRAGMENT_SHADER),
            validate=False)
        yield linked
        GL.glDeleteProgram(linked)


def _drawn(program, kind, params, points):
    """``zoneDistance`` for each of ``points``, as the shader works it out."""
    count = len(points)
    texture = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA32F, count, 1, 0, GL.GL_RGBA,
                    GL.GL_FLOAT, None)
    framebuffer = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, texture, 0)
    vao = GL.glGenVertexArrays(1)
    buffer = GL.glGenBuffers(1)
    try:
        assert GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE
        GL.glViewport(0, 0, count, 1)
        GL.glClearColor(1e6, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(program)
        GL.glUniform1i(GL.glGetUniformLocation(program, 'count'), count)
        GL.glUniform1i(GL.glGetUniformLocation(program, 'zoneKind[0]'),
                       zones.shader_kind(kind))
        shape = (tuple(params) + (0.0, 0.0, 0.0, 0.0))[:4]
        GL.glUniform4f(GL.glGetUniformLocation(program, 'zoneShape[0]'), *shape)
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buffer)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, np.ascontiguousarray(points, 'f4'),
                        GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glDrawArrays(GL.GL_POINTS, 0, count)
        raw = GL.glReadPixels(0, 0, count, 1, GL.GL_RED, GL.GL_FLOAT)
        return np.frombuffer(raw, dtype='f4').reshape(-1)[:count].astype('d')
    finally:
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        GL.glDeleteBuffers(1, [buffer])
        GL.glDeleteVertexArrays(1, [vao])
        GL.glDeleteFramebuffers(1, [framebuffer])
        GL.glDeleteTextures([texture])


@pytest.mark.parametrize('kind, params, spread', SHAPES,
                         ids=['%s-%s' % (kind, '-'.join('%g' % v for v in params))
                              for kind, params, _spread in SHAPES])
def test_the_shader_measures_as_the_arithmetic_does(program, kind, params, spread):
    rng = np.random.default_rng(abs(hash((kind, params))) % 2 ** 32)
    points = rng.uniform(-spread, spread, (COUNT, 3))
    points[:8] = 0.0                                  # the centre, several times
    wanted = zones._distance(kind, params, points)
    found = _drawn(program, kind, params, points)
    assert (wanted < 0).any() and (wanted > 0).any()  # both sides of the surface
    assert found == pytest.approx(wanted, abs=2e-4)
