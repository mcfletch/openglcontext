"""One table of vertex attribute locations, and everything that must match it."""
import os
import re

import pytest
from OpenGL.GL import glGetAttribLocation

from OpenGLContext.scenegraph import vertexsemantics as vs

SHADER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'OpenGLContext', 'shaders',
)

#: ``layout(location = 3) in vec4 aTangent;`` and every spacing of it.
DECLARATION = re.compile(
    r'layout\s*\(\s*location\s*=\s*(\d+)\s*\)\s*in\s+\w+\s+(\w+)\s*;'
)


def shader_declarations():
    """(file, location, attribute name) for every vertex input the shaders declare."""
    for name in sorted(os.listdir(SHADER_DIR)):
        if not name.endswith(('.vert', '.glsl')):
            continue
        with open(os.path.join(SHADER_DIR, name)) as source:
            text = source.read()
        for location, attribute in DECLARATION.findall(text):
            yield name, int(location), attribute


class TestTheTable:
    def test_a_semantic_answers_with_its_location(self):
        assert vs.location('POSITION') == 2
        assert vs.location('NORMAL') == 1
        assert vs.location('TEXCOORD_0') == 0
        assert vs.location('COLOR_0') == 4

    def test_an_unknown_semantic_is_named_in_the_error(self):
        with pytest.raises(KeyError) as caught:
            vs.location('SPARKLE_0')
        assert 'SPARKLE_0' in str(caught.value)

    def test_no_two_semantics_share_a_location(self):
        locations = [entry.location for entry in vs.SEMANTICS]
        assert len(set(locations)) == len(locations)

    def test_the_reserved_range_is_clear_of_the_semantics(self):
        reserved = set(range(vs.INSTANCE_MODELVIEW, vs.INSTANCE_MODELVIEW + 4))
        reserved |= {vs.INSTANCE_OBJECT_ID, vs.INSTANCE_MATERIAL,
                     vs.INSTANCE_JOINT_BASE}
        assert not reserved & {entry.location for entry in vs.SEMANTICS}

    def test_a_new_input_starts_above_everything_spoken_for(self):
        spoken_for = {entry.location for entry in vs.SEMANTICS}
        spoken_for |= {vs.INSTANCE_OBJECT_ID, vs.INSTANCE_MATERIAL,
                       vs.INSTANCE_JOINT_BASE}
        spoken_for |= set(range(vs.INSTANCE_MODELVIEW, vs.INSTANCE_MODELVIEW + 4))
        assert vs.FIRST_FREE_LOCATION == max(spoken_for) + 1


class TestTheShadersMatchIt:
    def test_every_shader_naming_a_semantic_reads_it_where_the_table_says(self):
        wrong = [
            '%s: %s at %d, the table says %d'
            % (name, attribute, location, vs.BY_ATTRIBUTE[attribute].location)
            for name, location, attribute in shader_declarations()
            if attribute in vs.BY_ATTRIBUTE
            and location != vs.BY_ATTRIBUTE[attribute].location
        ]
        assert not wrong, '\n'.join(wrong)

    def test_no_shader_puts_its_own_input_on_a_reserved_location(self):
        reserved = {
            vs.INSTANCE_OBJECT_ID: 'aInstanceObjectId',
            vs.INSTANCE_MATERIAL: 'aInstanceMaterial',
            vs.INSTANCE_JOINT_BASE: 'aInstanceJointBase',
        }
        for offset in range(4):
            reserved[vs.INSTANCE_MODELVIEW + offset] = 'aInstanceModelView'
        intruders = [
            '%s: %s at %d, which belongs to %s'
            % (name, attribute, location, reserved[location])
            for name, location, attribute in shader_declarations()
            if location in reserved and attribute != reserved[location]
            # A raw-GL layer that never meets the instanced draw path numbers
            # its own per-instance inputs from zero.
            and name.startswith(('vrml97_', 'pbr', 'shadow_', '_'))
        ]
        assert not intruders, '\n'.join(intruders)


class TestThePassAgreesWithIt:
    def test_every_compiled_program_reads_position_where_the_table_says(self, gl_context):
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        shader_program = VRML97ShaderProgram()
        assert shader_program.compile(), 'the VRML97 programs did not compile'
        for attribute in ('aPosition', 'aNormal', 'aTexCoord', 'aColor'):
            expected = vs.BY_ATTRIBUTE[attribute].location
            for held in VRML97ShaderProgram._PROGRAM_ATTRS:
                program = getattr(shader_program, held, None)
                if not program:
                    continue
                found = glGetAttribLocation(program, attribute)
                assert found in (-1, expected), (
                    '%s reads %s at %d, the table says %d'
                    % (held, attribute, found, expected))
