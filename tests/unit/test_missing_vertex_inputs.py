"""A shader reading an array it cannot draw without says so.

An attribute nothing feeds is not a GL error: the draw goes ahead, reading one
default value for every vertex. Where the shader has no meaning for that default
the shape comes out flat, or black, or gathered at the origin, and nothing in the
log says why. This is the check that names it -- and the declaration in the
shader source that keeps it from naming the inputs an uber-shader is written to
be drawn without.
"""
import numpy as np
import pytest
from OpenGL.GL import GL_FRAGMENT_SHADER, GL_VERTEX_SHADER
from OpenGL.GL import shaders as gl_shaders
from OpenGL.arrays import vbo

from OpenGLContext.passes.shadersource import (
    input_markers, required_inputs,
)
from OpenGLContext.scenegraph import vertexsemantics
from OpenGLContext.scenegraph.geometryarrays import (
    GeometryArrays, MissingVertexInput, forget_checked_programs,
    program_inputs, report_missing_inputs,
)

FRAGMENT = """#version 330 core
out vec4 fragColor;
void main() { fragColor = vec4(1.0); }
"""


def program_reading(*declarations):
    source = '#version 330 core\n%s\nvoid main() { gl_Position = vec4(%s); }' % (
        '\n'.join('in vec4 %s;' % (name,) for name in declarations),
        ' + '.join(declarations) if declarations else '0.0,0.0,0.0,1.0',
    )
    return gl_shaders.compileProgram(
        gl_shaders.compileShader(source, GL_VERTEX_SHADER),
        gl_shaders.compileShader(FRAGMENT, GL_FRAGMENT_SHADER),
    )


def a_buffer():
    return vbo.VBO(np.zeros((3, 3), dtype='f'))


class Pass:
    """Enough of a render pass to collect what was reported."""

    def __init__(self):
        self.reported = []

    def renderFailed(self, where, node, err):
        self.reported.append((where, node, err))


@pytest.fixture(autouse=True)
def a_fresh_record():
    forget_checked_programs()
    yield
    forget_checked_programs()


class TestWhatAShaderSaysAboutItsInputs:
    """Each vertex input is marked at its declaration as required or optional."""

    def test_each_declaration_carries_its_marker(self):
        source = ('layout(location = 2) in vec3 aPosition;  // required\n'
                  'layout( location=3 ) in vec4 aTangent; // optional: zero\n')
        assert input_markers(source) == {
            'aPosition': 'required', 'aTangent': 'optional'}

    def test_an_unmarked_declaration_claims_nothing(self):
        assert input_markers('layout(location = 4) in vec4 aColor;\n') == {
            'aColor': ''}

    def test_the_marker_is_the_declarations_own_comment(self):
        source = ('// required for the lit pass\n'
                  'layout(location = 4) in vec4 aColor;\n'
                  'uniform bool required;\n')
        assert input_markers(source) == {'aColor': ''}


class TestWhatTheEnginesShadersRequire:
    """The uber-shader declares more than any one geometry carries."""

    def test_the_pbr_program_needs_a_position_and_a_normal(self):
        assert required_inputs('pbr.vert') == frozenset(
            ['aPosition', 'aNormal'])

    def test_the_pbr_program_draws_without_the_optional_arrays(self):
        """A box has no tangent, no colour, no second UV set and no skin."""
        optional = {'aTangent', 'aColor', 'aTexCoord', 'aTexCoord1',
                    'aJoints', 'aWeights'}
        assert not (optional & required_inputs('pbr.vert'))

    def test_the_depth_program_needs_only_a_position(self):
        assert required_inputs('shadow_depth.vert') == frozenset(['aPosition'])

    def test_a_program_that_exists_for_the_colours_needs_them(self):
        for name in ('vrml97_point.vert', 'vrml97_line.vert',
                     'vrml97_vertex_color.vert'):
            assert 'aColor' in required_inputs(name), name

    def test_every_program_a_pass_binds_says_what_it_needs(self):
        """A declaration whose optionality is unstated is one nobody decided."""
        from OpenGLContext.passes.pbrpass import PBRShaderProgram
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        from OpenGLContext.passes.shadersource import preprocess_shader

        unmarked = []
        for name in sorted(set(PBRShaderProgram.VERTEX_SOURCES.values())
                           | set(VRML97ShaderProgram.VERTEX_SOURCES.values())):
            for attribute, marker in input_markers(
                    preprocess_shader(name)).items():
                if attribute in vertexsemantics.BY_ATTRIBUTE and not marker:
                    unmarked.append('%s: %s' % (name, attribute))
        assert not unmarked, '\n'.join(unmarked)


class TestTheProgramAnswersForWhatIsBound:
    def test_the_depth_program_asks_for_less_than_the_lit_one(self, gl_context):
        from OpenGLContext.passes.pbrpass import PBRShaderProgram

        shader_program = PBRShaderProgram()
        assert shader_program.compile(), 'the PBR programs did not compile'
        assert shader_program.required_inputs(shader_program.program) == (
            frozenset(['aPosition', 'aNormal']))
        shader_program.use_depth()
        assert shader_program.required_inputs() == frozenset(['aPosition'])

    def test_an_appearances_own_program_is_owed_nothing(self):
        """What a Shader node's GLSL can be drawn without is its author's."""
        from OpenGLContext.passes.shaderpass import ShaderAppearanceProgram

        appearance = ShaderAppearanceProgram(7)
        assert appearance.bound_program() == 7
        assert appearance.required_inputs() == frozenset()

    def test_a_program_from_somewhere_else_is_owed_nothing(self, gl_context):
        """Only the shaders the engine compiled are ones it can speak for."""
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

        shader_program = VRML97ShaderProgram()
        assert shader_program.compile(), 'the VRML97 programs did not compile'
        assert shader_program.required_inputs(program_reading('aPosition')) == (
            frozenset())


class TestWhatAProgramReads:
    def test_the_active_attributes_are_the_ones_declared_and_used(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        assert set(program_inputs(program)) == {'aPosition', 'aNormal'}


class TestTheReport:
    def test_an_array_the_geometry_lacks_is_named(self, gl_context):
        program = program_reading('aPosition', 'aTangent')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        err = report_missing_inputs(
            program, arrays, {'aPosition', 'aTangent'}, mode=pass_,
            where='opaque')
        assert isinstance(err, MissingVertexInput)
        assert 'aTangent' in str(err)
        assert 'aPosition' not in str(err)
        assert len(pass_.reported) == 1
        assert pass_.reported[0][0] == 'opaque'

    def test_an_array_the_shader_can_do_without_is_not_reported(self, gl_context):
        """The case an uber-shader is in on every ordinary box."""
        program = program_reading('aPosition', 'aTangent')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        assert report_missing_inputs(
            program, arrays, {'aPosition'}, mode=pass_) is None
        assert pass_.reported == []

    def test_a_geometry_that_supplies_everything_is_not_reported(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        arrays = GeometryArrays.separate(
            count=3, positions=a_buffer(), normals=a_buffer())
        pass_ = Pass()
        assert report_missing_inputs(
            program, arrays, {'aPosition', 'aNormal'}, mode=pass_) is None
        assert pass_.reported == []

    def test_an_input_compiled_out_of_the_program_is_not_owed(self, gl_context):
        """The driver's copy is the authority: no aWeights, nothing to feed."""
        program = program_reading('aPosition')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        assert report_missing_inputs(
            program, arrays, {'aPosition', 'aWeights'}, mode=pass_) is None

    def test_a_shader_the_engine_does_not_speak_for_is_owed_nothing(self, gl_context):
        """A ``Shader`` node's own GLSL: its defaults are its author's business."""
        program = program_reading('aPosition', 'sparkleAmount')
        arrays = GeometryArrays.separate(count=3)
        pass_ = Pass()
        assert report_missing_inputs(
            program, arrays, frozenset(), mode=pass_) is None
        assert pass_.reported == []

    def test_it_is_said_once_rather_than_once_a_frame(self, gl_context):
        program = program_reading('aPosition', 'aTangent')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        for _frame in range(5):
            report_missing_inputs(
                program, arrays, {'aPosition', 'aTangent'}, mode=pass_)
        assert len(pass_.reported) == 1

    def test_a_geometry_with_more_to_offer_is_checked_on_its_own(self, gl_context):
        """The record is per program and per set of arrays, not per program."""
        program = program_reading('aPosition', 'aTangent')
        required = {'aPosition', 'aTangent'}
        pass_ = Pass()
        report_missing_inputs(
            program, GeometryArrays.separate(count=3, positions=a_buffer()),
            required, mode=pass_)
        assert report_missing_inputs(
            program,
            GeometryArrays.separate(
                count=3, positions=a_buffer(), tangents=a_buffer()),
            required, mode=pass_) is None
        assert len(pass_.reported) == 1

    def test_a_pass_that_keeps_no_log_still_gets_the_answer(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        err = report_missing_inputs(
            program, arrays, {'aPosition', 'aNormal'}, mode=None)
        assert 'aNormal' in str(err)
