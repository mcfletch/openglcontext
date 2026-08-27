"""A shader reading an array the geometry has not got says so.

An attribute nothing feeds is not a GL error: the draw goes ahead, reading one
default value for every vertex. The shape comes out flat, or black, or gathered
at the origin, and nothing in the log says why. This is the check that names it.
"""
import numpy as np
import pytest
from OpenGL.GL import GL_FRAGMENT_SHADER, GL_VERTEX_SHADER
from OpenGL.GL import shaders as gl_shaders
from OpenGL.arrays import vbo

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


class TestWhatAProgramReads:
    def test_the_active_attributes_are_the_ones_declared_and_used(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        assert set(program_inputs(program)) == {'aPosition', 'aNormal'}


class TestTheReport:
    def test_an_array_the_geometry_lacks_is_named(self, gl_context):
        program = program_reading('aPosition', 'aTangent')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        err = report_missing_inputs(program, arrays, mode=pass_, where='opaque')
        assert isinstance(err, MissingVertexInput)
        assert 'aTangent' in str(err)
        assert 'aPosition' not in str(err)
        assert len(pass_.reported) == 1
        assert pass_.reported[0][0] == 'opaque'

    def test_a_geometry_that_supplies_everything_is_not_reported(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        arrays = GeometryArrays.separate(
            count=3, positions=a_buffer(), normals=a_buffer())
        pass_ = Pass()
        assert report_missing_inputs(program, arrays, mode=pass_) is None
        assert pass_.reported == []

    def test_a_shaders_own_input_is_its_own_business(self, gl_context):
        """A name the engine does not supply is not a name the engine owes."""
        program = program_reading('aPosition', 'sparkleAmount')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        assert report_missing_inputs(program, arrays, mode=pass_) is None

    def test_it_is_said_once_rather_than_once_a_frame(self, gl_context):
        program = program_reading('aPosition', 'aTangent')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        pass_ = Pass()
        for _frame in range(5):
            report_missing_inputs(program, arrays, mode=pass_)
        assert len(pass_.reported) == 1

    def test_a_geometry_with_more_to_offer_is_checked_on_its_own(self, gl_context):
        """The record is per program and per set of arrays, not per program."""
        program = program_reading('aPosition', 'aTangent')
        pass_ = Pass()
        report_missing_inputs(
            program, GeometryArrays.separate(count=3, positions=a_buffer()),
            mode=pass_)
        assert report_missing_inputs(
            program,
            GeometryArrays.separate(
                count=3, positions=a_buffer(), tangents=a_buffer()),
            mode=pass_) is None
        assert len(pass_.reported) == 1

    def test_a_pass_that_keeps_no_log_still_gets_the_answer(self, gl_context):
        program = program_reading('aPosition', 'aNormal')
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        err = report_missing_inputs(program, arrays, mode=None)
        assert 'aNormal' in str(err)
