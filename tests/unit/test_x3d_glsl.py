"""X3D's GLSL binding without GL: shader text, values, attribute places, linking

`OpenGLContext.scenegraph.x3dglsl` is the part of the X3D shader nodes that
needs no context. The texts it prepares are also compiled here, against a
real 3.30 core context, since a translation is only right if a compiler
takes it.
"""
import math

import numpy as np
import pytest
from OpenGL import GL
from OpenGL.GL import shaders as GL_shaders

from OpenGLContext.scenegraph import vertexsemantics, x3dglsl
from OpenGLContext.scenegraph.basenodes import (
    DirectionalLight, Material, PointLight, SpotLight,
)
from vrml.x3d import nodes as x3d


class TestStagesAndSources:
    def test_a_part_type_names_its_stage_whatever_its_case(self):
        assert x3dglsl.stage_of('vertex') == 'VERTEX'
        assert x3dglsl.stage_of(' Fragment ') == 'FRAGMENT'
        assert x3dglsl.stage_of('TESS_EVALUATION') == 'TESS_EVALUATION'

    def test_a_type_with_no_stage_is_none(self):
        assert x3dglsl.stage_of('COMPUTE') is None
        assert x3dglsl.stage_of('') is None

    def test_glsl_and_no_language_are_run_and_others_are_not(self):
        assert x3dglsl.speaks_glsl('GLSL')
        assert x3dglsl.speaks_glsl('')
        assert not x3dglsl.speaks_glsl('Cg')
        assert not x3dglsl.speaks_glsl('HLSL')

    def test_a_data_uri_holds_its_text(self):
        assert x3dglsl.inline_source('data:text/plain,void%20main(){}') == 'void main(){}'
        assert x3dglsl.inline_source(
            'data:text/plain;base64,dm9pZCBtYWluKCl7fQ==') == 'void main(){}'

    def test_text_written_into_the_url_is_the_source(self):
        source = 'void main() { gl_FragColor = vec4(1.0); }'
        assert x3dglsl.inline_source(source) == source
        assert x3dglsl.inline_source('\nuniform float a;\n') == '\nuniform float a;\n'

    def test_a_reference_to_a_file_holds_no_text(self):
        assert x3dglsl.inline_source('toon.fs') is None
        assert x3dglsl.inline_source('https://example.com/shaders/toon.frag') is None

    def test_the_version_and_profile_are_read_past_comments(self):
        assert x3dglsl.glsl_version('// header\n#version 330 core\n') == (330, 'core')
        assert x3dglsl.glsl_version('/* a\n b */\n#version 300 es\n') == (300, 'es')
        assert x3dglsl.glsl_version('void main(){}') == (None, '')

    def test_a_packaged_text_holds_the_stages_it_tests_for(self):
        text = '#ifdef X3D_VERTEX_SHADER\n#endif\n#ifdef X3D_GEOMETRY_SHADER\n#endif\n'
        assert x3dglsl.packaged_stages(text) == ['VERTEX', 'GEOMETRY']
        assert x3dglsl.packaged_stages('void main(){}') == ['VERTEX', 'FRAGMENT']


MODERN_VERTEX = """// a comment before the version
#version 330 core
#extension GL_ARB_explicit_attrib_location : enable
in vec4 x3d_Vertex;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
uniform x3d_LightSourceParameters x3d_LightSource[x3d_MaxLights];
void main() { gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex; }
"""


class TestPreparedText:
    def test_the_definitions_come_after_the_version_and_extensions(self):
        text = x3dglsl.prepare_source(MODERN_VERTEX, 'VERTEX').text
        lines = text.splitlines()
        assert lines[0] == '#version 330 core'
        assert lines.index('#define X3D_VERTEX_SHADER ') > lines.index(
            '#extension GL_ARB_explicit_attrib_location : enable')
        assert '#define x3d_MaxLights 8' in lines

    def test_a_structure_the_part_names_is_defined_once(self):
        text = x3dglsl.prepare_source(MODERN_VERTEX, 'VERTEX').text
        assert text.count('struct x3d_LightSourceParameters') == 1
        assert 'struct x3d_MaterialParameters' not in text

    def test_a_structure_the_part_defines_itself_is_left_to_it(self):
        own = MODERN_VERTEX.replace(
            'uniform x3d_Light',
            'struct x3d_LightSourceParameters { int type; };\nuniform x3d_Light')
        text = x3dglsl.prepare_source(own, 'VERTEX').text
        assert text.count('struct x3d_LightSourceParameters') == 1

    def test_the_body_keeps_its_line_numbers(self):
        text = x3dglsl.prepare_source(MODERN_VERTEX, 'VERTEX').text
        lines = text.splitlines()
        directive = next(i for i, line in enumerate(lines) if line.startswith('#line'))
        assert lines[directive] == '#line 4'
        assert lines[directive + 1] == 'in vec4 x3d_Vertex;'

    def test_the_maximum_lights_is_the_passs(self):
        assert '#define x3d_MaxLights 3' in x3dglsl.prepare_source(
            MODERN_VERTEX, 'VERTEX', max_lights=3).text

    def test_an_es3_part_is_compiled_as_desktop_330(self):
        prepared = x3dglsl.prepare_source(
            '#version 300 es\nprecision highp float;\nvoid main(){}\n', 'VERTEX')
        assert prepared.text.startswith('#version 330 core\n')
        assert not prepared.legacy

    def test_a_fragment_main_also_writes_the_object_id(self):
        prepared = x3dglsl.prepare_source(
            '#version 330 core\nout vec4 colour;\nvoid main() { colour = vec4(1.0); }\n',
            'FRAGMENT')
        assert 'void oglc_x3d_main(' in prepared.text
        assert x3dglsl.OBJECT_ID_OUTPUT in prepared.text
        assert prepared.has_main
        assert prepared.outputs == ['colour']

    def test_a_fragment_part_without_main_is_left_as_it_is(self):
        prepared = x3dglsl.prepare_source(
            '#version 330 core\nvec4 shade() { return vec4(1.0); }\n', 'FRAGMENT')
        assert not prepared.has_main
        assert x3dglsl.OBJECT_ID_OUTPUT not in prepared.text

    def test_no_object_id_when_it_is_not_asked_for(self):
        prepared = x3dglsl.prepare_source(
            '#version 330 core\nout vec4 c;\nvoid main() { c = vec4(1.0); }\n',
            'FRAGMENT', object_id=False)
        assert 'oglc_x3d_main' not in prepared.text


LEGACY_VERTEX = """varying vec3 normal;
attribute float heat;
uniform sampler2D texture;
void main() {
    normal = gl_NormalMatrix * gl_Normal;
    gl_TexCoord[0] = gl_TextureMatrix[0] * gl_MultiTexCoord0;
    vec4 eye = gl_ModelViewMatrixInverse * vec4(0.0, 0.0, 0.0, 1.0);
    vec3 toLight = gl_LightSource[0].position.xyz - eye.xyz;
    gl_FrontColor = gl_Color * heat + vec4(toLight, 0.0);
    gl_Position = ftransform();
}
"""

LEGACY_FRAGMENT = """varying vec3 normal;
uniform sampler2D texture;
void main() {
    vec4 c = texture2D(texture, gl_TexCoord[0].st);
    gl_FragColor = c * gl_Color * gl_FrontMaterial.diffuse;
}
"""


class TestLegacyTranslation:
    def test_a_part_with_no_version_is_translated(self):
        prepared = x3dglsl.prepare_source(LEGACY_VERTEX, 'VERTEX')
        assert prepared.legacy
        assert prepared.text.startswith('#version 330 core\n')

    def test_the_built_in_inputs_become_the_x3d_ones(self):
        text = x3dglsl.prepare_source(LEGACY_VERTEX, 'VERTEX').text
        assert 'in vec4 x3d_Vertex;' in text
        assert 'in vec3 x3d_Normal;' in text
        assert 'in vec4 x3d_TexCoord0;' in text
        assert 'gl_Vertex' not in text and 'ftransform' not in text

    def test_attribute_and_varying_become_in_and_out(self):
        vertex = x3dglsl.prepare_source(LEGACY_VERTEX, 'VERTEX').text
        fragment = x3dglsl.prepare_source(LEGACY_FRAGMENT, 'FRAGMENT').text
        assert 'out vec3 normal;' in vertex and 'in float heat;' in vertex
        assert 'in vec3 normal;' in fragment

    def test_an_identifier_330_reserves_is_renamed(self):
        prepared = x3dglsl.prepare_source(LEGACY_FRAGMENT, 'FRAGMENT')
        assert prepared.renamed == {'texture': 'oglc_texture'}
        assert 'texture(oglc_texture, oglc_TexCoord[0].st)' in prepared.text

    def test_the_colour_output_is_at_location_zero(self):
        prepared = x3dglsl.prepare_source(LEGACY_FRAGMENT, 'FRAGMENT')
        assert 'layout(location = 0) out vec4 oglc_FragColor;' in prepared.text
        assert x3dglsl.LEGACY_OUTPUT in prepared.outputs

    def test_a_name_the_part_declares_itself_is_not_declared_again(self):
        source = 'uniform mat4 x3d_ModelViewMatrix;\nvoid main(){ gl_Position = gl_ModelViewMatrix * gl_Vertex; }\n'
        text = x3dglsl.prepare_source(source, 'VERTEX').text
        assert text.count('uniform mat4 x3d_ModelViewMatrix;') == 1

    def test_comments_do_not_rename_or_declare(self):
        text = x3dglsl.prepare_source(
            '// uses gl_Normal one day\nvoid main(){ gl_Position = gl_Vertex; }\n',
            'VERTEX').text
        assert 'in vec3 x3d_Normal;' not in text


def _compile(text, stage):
    kind = {'VERTEX': GL.GL_VERTEX_SHADER, 'FRAGMENT': GL.GL_FRAGMENT_SHADER,
            'GEOMETRY': GL.GL_GEOMETRY_SHADER}[stage]
    shader = GL_shaders.compileShader(text, kind)
    return shader


@pytest.mark.usefixtures('gl_context')
class TestTheTextsCompile:
    """A translation is right only where a 3.30 core compiler takes it"""

    def test_a_translated_pair_compiles_and_links(self):
        vertex = _compile(x3dglsl.prepare_source(LEGACY_VERTEX, 'VERTEX').text, 'VERTEX')
        fragment = _compile(
            x3dglsl.prepare_source(LEGACY_FRAGMENT, 'FRAGMENT').text, 'FRAGMENT')
        program = GL_shaders.compileProgram(vertex, fragment, validate=False)
        try:
            assert GL.glGetUniformLocation(program, 'oglc_texture') != -1
            assert GL.glGetUniformLocation(program, 'oglc_LightSource[0].position') != -1
            assert GL.glGetAttribLocation(program, 'x3d_Vertex') != -1
        finally:
            GL.glDeleteProgram(program)

    def test_a_modern_part_compiles_with_the_structures(self):
        shader = _compile(x3dglsl.prepare_source(MODERN_VERTEX, 'VERTEX').text, 'VERTEX')
        try:
            assert GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS) == GL.GL_TRUE
        finally:
            GL.glDeleteShader(shader)

    def test_every_built_in_the_translation_names_compiles(self):
        vertex = ('void main() {\n'
                  '  vec4 a = gl_ModelViewProjectionMatrixInverseTranspose * gl_Vertex;\n'
                  '  a += gl_ProjectionMatrixTranspose * gl_Color + gl_MultiTexCoord1;\n'
                  '  a += gl_FrontLightProduct[1].diffuse + gl_LightModel.ambient;\n'
                  '  a += gl_FrontLightModelProduct.sceneColor + gl_BackMaterial.specular;\n'
                  '  gl_BackColor = a; gl_FrontSecondaryColor = a; gl_FogFragCoord = gl_FogCoord;\n'
                  '  gl_ClipVertex = a; gl_Position = a * float(gl_MaxLights);\n'
                  '}\n')
        fragment = ('uniform sampler2DShadow s;\n'
                    'void main() { gl_FragData[0] = gl_SecondaryColor * gl_FogFragCoord'
                    ' * shadow2D(s, vec3(0.0)).r; }\n')
        shaders = [_compile(x3dglsl.prepare_source(vertex, 'VERTEX').text, 'VERTEX'),
                   _compile(x3dglsl.prepare_source(fragment, 'FRAGMENT').text, 'FRAGMENT')]
        try:
            assert all(GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS) == GL.GL_TRUE
                       for shader in shaders)
        finally:
            for shader in shaders:
                GL.glDeleteShader(shader)

    def test_a_compile_error_names_the_line_in_the_part(self):
        broken = '#version 330 core\nin vec4 x3d_Vertex;\n\nvoid main() { oops; }\n'
        with pytest.raises(RuntimeError) as raised:
            _compile(x3dglsl.prepare_source(broken, 'VERTEX').text, 'VERTEX')
        assert ':4' in str(raised.value) or '(4)' in str(raised.value)


class TestUniformValues:
    def test_booleans_and_integers_are_integers(self):
        found = x3dglsl.uniform_values('SFBool', True)
        assert found.integer and found.width == 1 and list(found.values) == [1]
        assert list(x3dglsl.uniform_values('MFInt32', [3, -4]).values) == [3, -4]

    def test_doubles_and_times_are_floats(self):
        assert x3dglsl.uniform_values('SFDouble', 0.25).values.dtype == np.float32
        assert x3dglsl.uniform_values('SFTime', 12.5).values[0] == 12.5

    def test_vectors_colours_and_rotations_have_their_widths(self):
        assert x3dglsl.uniform_values('SFVec2f', (1, 2)).width == 2
        assert x3dglsl.uniform_values('SFColor', (1, 0, 0)).width == 3
        assert x3dglsl.uniform_values('SFRotation', (0, 1, 0, 1.5)).width == 4
        assert x3dglsl.uniform_values('MFVec3f', [(1, 2, 3), (4, 5, 6)]).values.tolist() == [
            1, 2, 3, 4, 5, 6]

    def test_matrices_keep_x3ds_order(self):
        values = np.arange(16, dtype=float).reshape(4, 4)
        found = x3dglsl.uniform_values('SFMatrix4f', values)
        assert found.width == 16
        assert found.values.tolist() == list(range(16))

    def test_an_image_is_its_integers(self):
        found = x3dglsl.uniform_values('SFImage', [2, 1, 1, 0xFF, 0x00])
        assert found.integer and found.values.tolist() == [2, 1, 1, 255, 0]

    def test_strings_and_nodes_are_not_values(self):
        assert x3dglsl.uniform_values('SFString', 'a') is None
        assert x3dglsl.uniform_values('MFString', ['a']) is None
        assert x3dglsl.uniform_values('SFNode', None) is None

    def test_non_finite_floats_are_made_finite(self):
        found = x3dglsl.uniform_values('MFFloat', [math.nan, math.inf, -math.inf])
        assert np.isfinite(found.values).all()

    def test_a_value_is_fitted_to_the_declared_type(self):
        found = x3dglsl.uniform_values('SFInt32', 3)
        converted = x3dglsl.convert_uniform(found, 1, False, 1)
        assert converted.dtype == np.float32 and converted.tolist() == [3.0]

    def test_a_longer_array_is_cut_to_the_declaration(self):
        found = x3dglsl.uniform_values('MFFloat', [1, 2, 3, 4, 5])
        assert x3dglsl.convert_uniform(found, 1, False, 3).tolist() == [1, 2, 3]

    def test_values_making_no_whole_element_are_none(self):
        found = x3dglsl.uniform_values('MFFloat', [1, 2])
        assert x3dglsl.convert_uniform(found, 3, False, 1) is None


class TestAttributeLayout:
    def test_the_free_locations_come_first_then_the_per_instance_ones(self):
        assert x3dglsl.attribute_locations(16) == [5, 6, 7, 8, 9, 10, 14]
        assert x3dglsl.attribute_locations(18)[:3] == [16, 17, 5]

    def test_no_location_the_engine_feeds_is_offered(self):
        engine = {entry.location for entry in vertexsemantics.SEMANTICS}
        assert not engine & set(x3dglsl.attribute_locations(32))

    def test_a_matrix_takes_a_run_of_locations(self):
        layout = x3dglsl.attribute_layout([('heat', 1), ('frame', 4), ('shear', 3)], 24)
        assert layout == (('heat', 16), ('frame', 17), ('shear', 21))
        layout = x3dglsl.attribute_layout([('frame', 4), ('shear', 3)], 16)
        assert layout == (('frame', 5),)

    def test_an_attribute_that_does_not_fit_is_left_out(self):
        layout = x3dglsl.attribute_layout(
            [('a', 4), ('b', 4), ('c', 1), ('d', 1)], 16)
        assert dict(layout) == {'a': 5, 'c': 9, 'd': 10}

    def test_a_second_attribute_of_one_name_is_left_out(self):
        assert x3dglsl.attribute_layout([('a', 1), ('a', 1)], 32) == (('a', 16),)

    def test_a_float_attribute_groups_its_components(self):
        node = x3d.FloatVertexAttribute(name='heat', numComponents=2, value=[1, 2, 3, 4, 5])
        name, values, locations = x3dglsl.vertex_attribute(node)
        assert name == 'heat' and locations == 1
        assert values.tolist() == [[1, 2], [3, 4]]

    def test_a_matrix_attribute_is_one_matrix_a_vertex(self):
        node = x3d.Matrix3VertexAttribute(name='m', value=[np.eye(3), np.eye(3) * 2])
        name, values, locations = x3dglsl.vertex_attribute(node)
        assert values.shape == (2, 9) and locations == 3
        node = x3d.Matrix4VertexAttribute(name='m', value=[np.eye(4)])
        assert x3dglsl.vertex_attribute(node)[1:] == (pytest.approx(np.eye(4).reshape(1, 16)), 4)

    def test_an_attribute_without_a_name_is_none(self):
        assert x3dglsl.vertex_attribute(x3d.FloatVertexAttribute(value=[1.0])) is None

    def test_an_attribute_without_values_has_no_rows(self):
        name, values, locations = x3dglsl.vertex_attribute(
            x3d.FloatVertexAttribute(name='a', numComponents=3))
        assert (name, values.shape, locations) == ('a', (0, 3), 1)

    def test_the_widths_are_those_of_the_attributes_with_names(self):
        nodes = [x3d.FloatVertexAttribute(name='a'), x3d.FloatVertexAttribute(value=[1.0]),
                 x3d.Matrix3VertexAttribute(name='m'), x3d.Matrix4VertexAttribute(name='n')]
        assert x3dglsl.attribute_widths(nodes) == [('a', 1), ('m', 3), ('n', 4)]
        assert x3dglsl.attribute_widths(nodes) == [
            (name, locations) for name, _values, locations in x3dglsl.vertex_attributes(nodes)]

    def test_an_attribute_short_of_values_reads_zero_past_them(self):
        found, short = x3dglsl.per_vertex(
            [('a', np.array([[1.0], [2.0]], np.float32), 1)], np.array([0, 1, 2, 2]))
        assert short == ['a']
        assert found[0][1].ravel().tolist() == [1.0, 2.0, 0.0, 0.0]


class TestLightsAndMaterials:
    def test_a_directional_light_points_in_eye_space(self):
        light = DirectionalLight(direction=(0, 0, -1), color=(1, 0.5, 0), intensity=0.5)
        turned = np.eye(4)
        turned[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
        found = x3dglsl.light_parameters(light, turned)
        assert found['type'] == 1 and found['radius'] == -1.0
        assert found['direction'] == pytest.approx((1.0, 0.0, 0.0))
        assert found['intensity'] == 0.5

    def test_a_point_light_is_placed_by_its_matrix(self):
        light = PointLight(location=(1, 2, 3), radius=10, attenuation=(1, 0.5, 0))
        moved = np.eye(4)
        moved[3, :3] = (0, 0, -5)
        found = x3dglsl.light_parameters(light, moved)
        assert found['type'] == 2 and found['radius'] == 10
        assert found['location'] == pytest.approx((1, 2, -2))
        assert found['attenuation'] == pytest.approx((1, 0.5, 0))

    def test_a_spot_light_has_its_angles(self):
        light = SpotLight(cutOffAngle=0.5, beamWidth=0.25)
        found = x3dglsl.light_parameters(light, np.eye(4))
        assert found['type'] == 3
        assert (found['cutOffAngle'], found['beamWidth']) == (0.5, 0.25)

    def test_the_lights_matrix_measures_in_its_own_space(self):
        scaled = np.diag((2.0, 2.0, 2.0, 1.0))
        found = x3dglsl.light_parameters(PointLight(), scaled)
        assert found['matrix'] == pytest.approx(np.eye(3) / 2)

    def test_the_headlight_looks_along_the_view(self):
        found = x3dglsl.headlight_parameters()
        assert found['type'] == 1 and found['direction'].tolist() == [0, 0, -1]

    def test_the_legacy_light_of_a_directional_light_points_towards_it(self):
        light = x3dglsl.light_parameters(DirectionalLight(direction=(0, -1, 0)), np.eye(4))
        legacy = x3dglsl.legacy_light_parameters(light)
        assert legacy['position'] == pytest.approx((0, 1, 0, 0))
        assert legacy['spotCutoff'] == 180.0

    def test_the_legacy_light_of_a_spot_has_its_cutoff_in_degrees(self):
        light = x3dglsl.light_parameters(SpotLight(cutOffAngle=math.pi / 4), np.eye(4))
        legacy = x3dglsl.legacy_light_parameters(light)
        assert legacy['spotCutoff'] == pytest.approx(45.0)
        assert legacy['spotCosCutoff'] == pytest.approx(math.cos(math.pi / 4))
        assert legacy['position'][3] == 1.0

    def test_a_material_gives_its_own_fields(self):
        found = x3dglsl.material_parameters(Material(diffuseColor=(1, 0, 0), shininess=0.5))
        assert found['diffuseColor'] == pytest.approx((1, 0, 0))
        assert found['shininess'] == 0.5
        assert found['emissiveColor'] == pytest.approx((0, 0, 0))

    def test_a_physical_material_gives_its_base_colour(self):
        found = x3dglsl.material_parameters(x3d.PhysicalMaterial(baseColor=(0, 1, 0), metallic=0.25))
        assert found['baseColor'] == pytest.approx((0, 1, 0))
        assert found['metallic'] == 0.25

    def test_no_material_is_unlit_white(self):
        found = x3dglsl.material_parameters(None)
        assert found['emissiveColor'] == pytest.approx((1, 1, 1))
        assert found['diffuseColor'] == pytest.approx((0, 0, 0))

    def test_the_legacy_material_carries_transparency_in_diffuse_alpha(self):
        found = x3dglsl.legacy_material_parameters(x3dglsl.material_parameters(
            Material(diffuseColor=(1, 1, 1), transparency=0.25, shininess=0.5)))
        assert found['diffuse'][3] == pytest.approx(0.75)
        assert found['shininess'] == 64.0


class TestLinkSchedule:
    def test_the_first_complete_sources_are_linked(self):
        schedule = x3dglsl.LinkSchedule()
        assert not schedule.due(None)
        assert schedule.due(('a', 'b'))

    def test_a_running_program_is_kept_when_a_source_changes(self):
        schedule = x3dglsl.LinkSchedule()
        schedule.linked(('a', 'b'), ok=True)
        assert not schedule.due(('a', 'c'))

    def test_activate_links_again(self):
        schedule = x3dglsl.LinkSchedule()
        schedule.linked(('a', 'b'), ok=True)
        schedule.activate()
        assert schedule.due(('a', 'c'))
        schedule.linked(('a', 'c'), ok=True)
        assert not schedule.due(('a', 'd'))

    def test_a_failed_link_is_retried_when_the_sources_change(self):
        schedule = x3dglsl.LinkSchedule()
        schedule.linked(('a', 'b'), ok=False)
        assert not schedule.due(('a', 'b'))
        assert schedule.due(('a', 'fixed'))
