"""A ``Shader`` appearance's own GLSL program draws the shape's geometry.

``Shader`` is a programmable substitute for an ``Appearance``: it carries a GLSL
program instead of a material and a texture. The geometry and the program are
written by different people, so something has to say which vertex array feeds
which input, and that something is the location table in
``OpenGLContext.scenegraph.vertexsemantics``: ``GLSLObject.compile`` binds the
engine's own attribute names there before it links, and a shader that calls its
inputs something else says so with a ``ShaderInput``.
"""
import numpy as np
import pytest
from OpenGL.GL import glGetAttribLocation
from vrml import cache

from OpenGLContext.scenegraph import vertexsemantics as vs
from OpenGLContext.scenegraph.basenodes import Appearance, Box, Material, Sphere
from OpenGLContext.scenegraph.shaders import (
    GLSLObject, GLSLShader, Shader, ShaderInput,
)
from OpenGLContext.scenegraph.shape import Shape

VERTEX = """#version 330 core
in vec3 %s;
in vec3 aNormal;
uniform mat4 mat_modelproj;
out vec3 vNormal;
void main() {
    vNormal = aNormal;
    gl_Position = mat_modelproj * vec4(%s, 1.0);
}
"""

FRAGMENT = """#version 330 core
in vec3 vNormal;
out vec4 fragColor;
void main() { fragColor = vec4(abs(vNormal), 1.0); }
"""


class _PassProgram:
    """The pass's own program, which a ``Shader`` appearance stands aside for.

    A ``Shape`` configures the material and texture on it before handing the
    geometry over; none of that is what these tests are about, so it is taken
    and dropped.
    """

    program = 0

    #: What a Shape configures on the pass's shader before handing the geometry
    #: over. None of it is what these tests are about, so it is taken and
    #: dropped -- but only these, since `_render_shader` branches on which of
    #: them a program has.
    _ACCEPTED = (
        'set_material', 'set_default_material', 'set_texture_enabled',
        'set_texture_transform', 'set_default_texture_transform',
        'bind_texture', 'unbind_texture',
    )

    def __getattr__(self, name):
        if name in self._ACCEPTED:
            return lambda *args, **named: None
        raise AttributeError(name)


class _Mode:
    """Enough of a pass for a ``GLSLObject`` to compile and a ``Shape`` to draw."""

    shader_mode = True
    visible = True
    shadow_pass = False
    transparent = False
    uniforms = ()

    def __init__(self):
        self.cache = cache.Cache()
        self.matrix = np.identity(4, dtype='f')
        self.projection = np.identity(4, dtype='f')
        self.shader_program = _PassProgram()


def compiled(position_name='aPosition', attributes=(), source=None):
    """Compile a one-object shader and return (program, GLSLObject)."""
    obj = GLSLObject(
        shaders=[
            GLSLShader(
                source=[source or (VERTEX % (position_name, position_name))],
                type='VERTEX'),
            GLSLShader(source=[FRAGMENT], type='FRAGMENT'),
        ],
        attributes=list(attributes),
    )
    program = obj.compile(_Mode())
    assert program, obj.compileLog
    return program, obj


class TestTheEngineNamesAreBound:
    def test_a_shader_naming_the_engine_arrays_needs_no_declaration(self, gl_context):
        program, _ = compiled()
        assert glGetAttribLocation(program, 'aPosition') == vs.LOC_POSITION
        assert glGetAttribLocation(program, 'aNormal') == vs.LOC_NORMAL

    def test_a_shader_input_says_what_this_shader_calls_it(self, gl_context):
        program, _ = compiled(
            'vertexInput',
            [ShaderInput(semantic='POSITION', name='vertexInput')])
        assert glGetAttribLocation(program, 'vertexInput') == vs.LOC_POSITION
        # The names it did not rename still arrive where the table says.
        assert glGetAttribLocation(program, 'aNormal') == vs.LOC_NORMAL

    def test_a_layout_qualifier_in_the_source_outranks_the_table(self, gl_context):
        """GLSL 3.30 4.3.8.2: the qualifier wins over glBindAttribLocation."""
        source = (VERTEX % ('aPosition', 'aPosition')).replace(
            'in vec3 aPosition;', 'layout(location = 7) in vec3 aPosition;')
        program, _ = compiled(source=source)
        assert glGetAttribLocation(program, 'aPosition') == 7

    def test_an_unknown_semantic_is_reported_rather_than_bound_anywhere(self, gl_context):
        with pytest.raises(KeyError) as raised:
            compiled('vertexInput',
                     [ShaderInput(semantic='SPARKLE_0', name='vertexInput')])
        assert 'SPARKLE_0' in str(raised.value)


class TestTheShapeDraws:
    def test_the_geometry_is_drawn_with_the_appearances_own_program(self, gl_context):
        drawn = []
        shape = Shape(
            geometry=Sphere(radius=1.0),
            appearance=Shader(objects=[compiled()[1]]),
        )

        def record(*args, **named):
            drawn.append(named['mode'].shader_program.program)
            return 1

        shape.geometry.render = record
        mode = _Mode()
        shape.Render(mode=mode)
        assert drawn, 'the geometry was never asked to draw'
        assert glGetAttribLocation(drawn[0], 'aPosition') == vs.LOC_POSITION

    def test_the_pass_gets_its_own_program_back_afterwards(self, gl_context):
        shape = Shape(geometry=Box(), appearance=Shader(objects=[compiled()[1]]))
        mode = _Mode()
        sentinel = mode.shader_program
        shape.geometry.render = lambda *a, **k: 1
        shape.Render(mode=mode)
        assert mode.shader_program is sentinel

    def test_selection_draws_with_the_passs_program_not_the_appearances(self, gl_context):
        """Picking paints an id colour; the appearance's shader would paint its own."""
        drawn = []
        shape = Shape(geometry=Box(), appearance=Shader(objects=[compiled()[1]]))
        shape.geometry.render = lambda *a, **k: drawn.append(
            k['mode'].shader_program)
        mode = _Mode()
        mode.visible = False
        shape.Render(mode=mode)
        assert drawn == [mode.shader_program]

    def test_a_shape_with_no_appearance_at_all_goes_through_the_pass(self, gl_context):
        """An unset SFNode field reads as a null node, not as ``None``."""
        drawn = []
        shape = Shape(geometry=Box())
        shape.geometry.render = lambda *a, **k: drawn.append(
            k['mode'].shader_program)
        mode = _Mode()
        shape.Render(mode=mode)
        assert drawn == [mode.shader_program]

    def test_an_ordinary_appearance_still_goes_through_the_pass(self, gl_context):
        """The branch must not catch the node every other shape in a scene uses."""
        drawn = []
        shape = Shape(geometry=Box(), appearance=Appearance(material=Material()))
        shape.geometry.render = lambda *a, **k: drawn.append(
            k['mode'].shader_program)
        mode = _Mode()
        shape.Render(mode=mode)
        assert drawn == [mode.shader_program]
