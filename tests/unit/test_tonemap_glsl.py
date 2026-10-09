"""The shaders' tone curves are the Python ones (GL).

``toneCurve`` and ``untoneCurve`` in ``_tonemap_inc.glsl`` are drawn for
colours spread over [0, 2], one per pixel of a float framebuffer, and read
back against :func:`OpenGLContext.passes.tonemapping.tone_map` and
:func:`~OpenGLContext.passes.tonemapping.untone`.
"""
import numpy as np
import pytest
from OpenGL import GL
from OpenGL.GL import shaders

from OpenGLContext.passes import tonemapping
from OpenGLContext.passes.shadersource import _resolve_includes
from OpenGLContext.testing.glcontext import gl_available, hidden_window

#: Colours per curve.
COUNT = 256

_VERTEX = '''#version 330 core
layout(location = 0) in vec3 aColour;
flat out vec3 vColour;
uniform int count;
void main() {
    vColour = aColour;
    float x = (float(gl_VertexID) + 0.5) / float(count) * 2.0 - 1.0;
    gl_Position = vec4(x, 0.0, 0.0, 1.0);
}
'''

_FRAGMENT = '''#version 330 core
#include "_tonemap_inc.glsl"
flat in vec3 vColour;
uniform bool inverse;
out vec4 colour;
void main() {
    colour = vec4(inverse ? untoneCurve(vColour) : toneCurve(vColour), 1.0);
}
'''


@pytest.fixture(scope='module')
def program():
    if not gl_available():
        pytest.skip('no GL context can be made here')
    with hidden_window('tone curves', size=(COUNT, 1)):
        linked = shaders.compileProgram(
            shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER),
            shaders.compileShader(_resolve_includes(_FRAGMENT, set()), GL.GL_FRAGMENT_SHADER),
            validate=False)
        yield linked
        GL.glDeleteProgram(linked)


def _drawn(program, operator, colours, inverse=False):
    """Each of ``colours`` through the shader's curve, or its inverse."""
    count = len(colours)
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
        GL.glUseProgram(program)
        GL.glUniform1i(GL.glGetUniformLocation(program, 'count'), count)
        GL.glUniform1i(GL.glGetUniformLocation(program, 'toneMapping'),
                       tonemapping.operator_code(operator))
        GL.glUniform1i(GL.glGetUniformLocation(program, 'inverse'), int(inverse))
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buffer)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, np.ascontiguousarray(colours, 'f4'),
                        GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glDrawArrays(GL.GL_POINTS, 0, count)
        raw = GL.glReadPixels(0, 0, count, 1, GL.GL_RGB, GL.GL_FLOAT)
        return np.frombuffer(raw, dtype='f4').reshape(-1, 3)[:count].astype('d')
    finally:
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        GL.glDeleteBuffers(1, [buffer])
        GL.glDeleteVertexArrays(1, [vao])
        GL.glDeleteFramebuffers(1, [framebuffer])
        GL.glDeleteTextures([texture])


@pytest.mark.parametrize('operator', tonemapping.OPERATORS)
def test_the_shader_curves_as_the_arithmetic_does(program, operator):
    colours = np.random.default_rng(3).uniform(0.0, 2.0, (COUNT, 3))
    colours[0] = (0.04, 0.5, 0.9)           # a dark minimum, for the Neutral offset
    found = _drawn(program, operator, colours)
    assert found == pytest.approx(tonemapping.tone_map(colours, operator), abs=2e-5)


@pytest.mark.parametrize('operator', tonemapping.OPERATORS)
def test_the_shader_inverts_as_the_arithmetic_does(program, operator):
    shown = np.random.default_rng(5).uniform(0.02, 0.95, (COUNT, 3))
    found = _drawn(program, operator, shown, inverse=True)
    assert found == pytest.approx(tonemapping.untone(shown, operator), rel=1e-3, abs=1e-4)
