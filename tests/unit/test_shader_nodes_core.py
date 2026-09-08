"""The declarative shader nodes draw under a core profile.

``GLSLObject``/``ShaderAttribute``/``ShaderGeometry`` are the scenegraph's own way
of writing a shader -- a shader as nodes rather than as GL calls.  Every vertex
attribute they set up goes through ``glVertexAttribPointer``, which in a core
profile records into the bound vertex array object; there is no default object 0
to record into, so with none bound every such call is
``GLError(1282, 'invalid operation')`` and the shape draws nothing.

The shader here is core GLSL, and takes its matrix from ``mat_modelproj``, which
is the uniform the render pass supplies for exactly this.
"""

import numpy as np
import pytest

pytest.importorskip("glfw")

pytest_plugins = ['tests.unit.test_passes_render_gl']

VERTEX = """#version 330 core
in vec3 position;
in vec3 Color;
uniform vec3 mixColor;
uniform mat4 mat_modelproj;
out vec4 baseColor;
void main() {
    gl_Position = mat_modelproj * vec4( position, 1.0 );
    baseColor = mix( vec4(mixColor,1.0), vec4(Color,1.0), .5 );
}"""

FRAGMENT = """#version 330 core
in vec4 baseColor;
out vec4 fragColor;
void main() { fragColor = baseColor; }"""

#: One triangle, interleaved position (3f) then colour (3f).
TRIANGLE = [
    [0, 1, -4, 0, 1, 0],
    [-1, -1, -4, 1, 1, 0],
    [1, -1, -4, 0, 1, 1],
]


@pytest.fixture(autouse=True)
def shader_paths(monkeypatch):
    """The VRML97 flat pass: these nodes render through its shader path."""
    from tests.unit.test_passes_render_gl import _base_env
    _base_env(monkeypatch)
    monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)


def shader_scene():
    from OpenGLContext.scenegraph.basenodes import Transform
    from OpenGLContext.scenegraph.shaders import (
        FloatUniform3f, GLSLObject, GLSLShader, Shader, ShaderAttribute,
        ShaderBuffer, ShaderGeometry, ShaderSlice,
    )

    buffer = ShaderBuffer(buffer=TRIANGLE)
    return [Transform(children=[ShaderGeometry(
        DEF='CoreShaderGeometry',
        slices=[ShaderSlice(offset=0, count=3)],
        uniforms=[FloatUniform3f(name='mixColor', value=[1.0, 0.0, 0.0])],
        attributes=[
            ShaderAttribute(name='position', offset=0, stride=24, size=3,
                            dataType='FLOAT', buffer=buffer, isCoord=True),
            ShaderAttribute(name='Color', offset=12, stride=24, size=3,
                            dataType='FLOAT', buffer=buffer),
        ],
        appearance=Shader(objects=[GLSLObject(shaders=[
            GLSLShader(source=[VERTEX], type='VERTEX'),
            GLSLShader(source=[FRAGMENT], type='FRAGMENT'),
        ])]),
    )])]


class TestShaderGeometryDrawsUnderCore:
    def test_nothing_failed_to_render(self, render_scene):
        from OpenGLContext.passes import renderpass
        render_scene(shader_scene(), frames=3)
        assert renderpass.FLAT.failures.summary() == []

    def test_the_triangle_reaches_the_framebuffer(self, render_scene):
        from OpenGLContext.capture import read_back_buffer
        from OpenGLContext import glfwcontext

        frames = []
        original = glfwcontext.GLFWContext.SwapBuffers

        def capturing(self):
            frames.append(read_back_buffer()[0])
            return original(self)

        glfwcontext.GLFWContext.SwapBuffers = capturing
        try:
            render_scene(shader_scene(), frames=4)
        finally:
            glfwcontext.GLFWContext.SwapBuffers = original
        assert frames, 'nothing was rendered'
        pixels = np.asarray(frames[-1])
        assert pixels.max() > 0, 'the frame is black'

    def test_the_attribute_arrays_do_not_leak_into_the_next_shape(self, render_scene):
        """Each shape's attribute state is its own, so two of them both draw."""
        from OpenGLContext.passes import renderpass
        render_scene(shader_scene() + shader_scene(), frames=3)
        assert renderpass.FLAT.failures.summary() == []
