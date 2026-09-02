"""Every VRML97 sub-program links, and its shadow samplers get their own unit.

Two things a driver will not let slide, and which only a real link shows:

* ``glValidateProgram`` answers against *current* GL state, so a program whose
  differently-targeted shadow samplers still all read texture unit 0 -- which
  is where they sit until the units are assigned -- validates as a failure.
  A driver that answers leniently hides it; this one does not.
* Those samplers have to be given distinct units whether or not shadows are
  switched on, because a draw with two active samplers of different targets on
  one unit is GL_INVALID_OPERATION either way.
"""

import ctypes

import pytest

from OpenGL.GL import (
    GL_LINK_STATUS,
    glGetProgramiv,
    glGetUniformiv,
    glGetUniformLocation,
)

from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

#: The handles compile() fills in, by the attribute each is kept on.
SUB_PROGRAMS = (
    'program',
    'unlit_program',
    'vertex_color_program',
    'point_program',
    'line_program',
    'depth_program',
)


@pytest.fixture
def compiled(gl_context):
    program = VRML97ShaderProgram()
    assert program.compile(), 'the lit program did not compile'
    return program


@pytest.mark.parametrize('attribute', SUB_PROGRAMS)
def test_every_sub_program_links(compiled, attribute):
    handle = getattr(compiled, attribute)
    assert handle is not None, '%s did not compile' % attribute
    assert glGetProgramiv(handle, GL_LINK_STATUS), '%s did not link' % attribute


def test_each_shadow_receiver_has_its_samplers_on_distinct_units(compiled):
    """Including when shadows are off -- compile() is what assigns them."""
    receivers = compiled.shadow_receiver_programs()
    assert compiled.vertex_color_program in receivers, (
        'the vertex-colour program samples shadows, so it is a receiver'
    )
    for handle in receivers:
        units = {}
        for name in ('shadowArray', 'shadowArrayRaw'):
            location = glGetUniformLocation(handle, name)
            if location == -1:
                continue  # optimised out of this program
            value = ctypes.c_int(0)
            glGetUniformiv(handle, location, value)
            units[name] = value.value
        assert len(set(units.values())) == len(units), (
            'program %r has shadow samplers sharing a texture unit: %r'
            % (handle, units)
        )
        assert 0 not in units.values(), (
            'program %r leaves a shadow sampler on unit 0, where the material '
            'texture lives: %r' % (handle, units)
        )
