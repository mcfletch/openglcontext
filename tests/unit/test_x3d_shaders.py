"""X3D's programmable shaders draw the shapes whose appearance lists them

A document's `Appearance.shaders` lists alternatives; the first whose language
the engine runs and whose program links draws the shape, and the others say
`isSelected FALSE`. Each case is a document drawn in a real context through
both renderers, and read back.
"""
import numpy as np
import pytest
from vrml import x3d as vrml_x3d

from OpenGLContext.loaders import background
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

RENDERERS = ('pbr', 'vrml97')

VERTEX = """<![CDATA[#version 330 core
in vec4 x3d_Vertex;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
void main() { gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex; }
]]>"""

FLAT = """<![CDATA[#version 330 core
uniform vec3 colour;
out vec4 fragColour;
void main() { fragColour = vec4(colour, 1.0); }
]]>"""


def composed(fragment=FLAT, vertex=VERTEX, fields='', attributes='', language='GLSL'):
    """A ComposedShader of a vertex and a fragment part"""
    return ('<ComposedShader DEF="S" language="%s" %s>%s'
            '<ShaderPart type="VERTEX">%s</ShaderPart>'
            '<ShaderPart type="FRAGMENT">%s</ShaderPart></ComposedShader>'
            % (language, attributes, fields, vertex, fragment))


def document(shaders, geometry='<Box size="4 4 4"/>',
             material='<Material diffuseColor="0 0 1"/>', texture='', scene=''):
    return ('<X3D profile="Full" version="4.0"><Scene>'
            '<Viewpoint position="0 0 10"/><NavigationInfo headlight="false"/>%s'
            '<Shape DEF="SHAPE"><Appearance>%s%s%s</Appearance>%s</Shape>'
            '</Scene></X3D>' % (scene, material, texture, shaders, geometry))


def load(text):
    scene = vrml_x3d.loads(text, prototypes=prototypes())
    errors = [str(problem) for problem in scene.problems if problem.severity == 'error']
    assert not errors, errors
    return scene


def named(scene, name):
    from vrml import protofunctions
    for node in _walk(scene):
        if protofunctions.defName(node) == name:
            return node
    raise KeyError(name)


def _walk(start):
    from vrml import node as vrml_node, protofunctions
    seen, pending = set(), [start]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for declared in protofunctions.getFields(current):
            if declared.typeName() not in ('SFNode', 'MFNode'):
                continue
            value = declared.fget(current)
            for child in (value if isinstance(value, list) else [value]):
                if isinstance(child, vrml_node.Node):
                    pending.append(child)


def centre(scene, renderer, frames=2, size=(64, 64)):
    """The colour at the middle of the frame after `frames` draws"""
    with scene_context(scene, size=size,
                       environment={'OPENGLCONTEXT_RENDERER': renderer}) as context:
        for _ in range(frames - 1):
            context.OnDraw(force=1)
        background.wait_for_idle()
        image = drawn_image(context)
    return image[size[1] // 2, size[0] // 2].astype(int)


def reddish(pixel):
    return pixel[0] > 150 and pixel[1] < 80 and pixel[2] < 80


def greenish(pixel):
    return pixel[1] > 150 and pixel[0] < 80 and pixel[2] < 80


def bluish(pixel):
    return pixel[2] > 100 and pixel[0] < 80 and pixel[1] < 80


@pytest.fixture(autouse=True)
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


@pytest.mark.parametrize('renderer', RENDERERS)
class TestTheShaderDraws:
    def test_a_field_is_the_uniform_of_its_name(self, renderer):
        scene = load(document(composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))
        assert reddish(centre(scene, renderer))
        shader = named(scene, 'S')
        assert shader.isSelected is True
        assert shader.isValid is True

    def test_setting_the_field_changes_the_uniform(self, renderer):
        scene = load(document(composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))
        shader = named(scene, 'S')
        with scene_context(scene, size=(64, 64),
                           environment={'OPENGLCONTEXT_RENDERER': renderer}) as context:
            assert reddish(drawn_image(context)[32, 32])
            shader.colour = (0, 1, 0)
            assert greenish(drawn_image(context)[32, 32])

    def test_an_input_only_field_takes_the_event_sent_to_it(self, renderer):
        scene = load(document(composed(
            fields='<field name="colour" type="SFColor" accessType="inputOnly"/>')))
        shader = named(scene, 'S')
        with scene_context(scene, size=(64, 64),
                           environment={'OPENGLCONTEXT_RENDERER': renderer}) as context:
            drawn_image(context)
            shader.colour = (0, 1, 0)
            assert greenish(drawn_image(context)[32, 32])

    def test_the_material_is_offered_as_x3d_material(self, renderer):
        fragment = """<![CDATA[#version 330 core
uniform x3d_MaterialParameters x3d_Material;
out vec4 c;
void main() { c = vec4(x3d_Material.diffuseColor, 1.0); }
]]>"""
        scene = load(document(composed(fragment),
                              material='<Material diffuseColor="0 1 0"/>'))
        assert greenish(centre(scene, renderer))

    def test_a_light_is_offered_as_x3d_light_source(self, renderer):
        fragment = """<![CDATA[#version 330 core
uniform x3d_LightSourceParameters x3d_LightSource[x3d_MaxLights];
out vec4 c;
void main() {
    x3d_LightSourceParameters light = x3d_LightSource[0];
    c = light.type == x3d_DirectionalLight ? vec4(light.color * light.intensity, 1.0)
                                           : vec4(0.0, 0.0, 1.0, 1.0);
}
]]>"""
        scene = load(document(
            composed(fragment),
            scene='<DirectionalLight color="0 1 0" intensity="1" direction="0 0 -1"/>'))
        assert greenish(centre(scene, renderer))

    def test_an_unset_light_slot_is_none(self, renderer):
        fragment = """<![CDATA[#version 330 core
uniform x3d_LightSourceParameters x3d_LightSource[x3d_MaxLights];
out vec4 c;
void main() {
    c = x3d_LightSource[1].type == x3d_NoneLight ? vec4(0.0, 1.0, 0.0, 1.0)
                                                 : vec4(1.0, 0.0, 0.0, 1.0);
}
]]>"""
        scene = load(document(composed(fragment),
                              scene='<DirectionalLight direction="0 0 -1"/>'))
        assert greenish(centre(scene, renderer))

    def test_the_appearance_texture_is_x3d_texture2d(self, renderer):
        fragment = """<![CDATA[#version 330 core
uniform sampler2D x3d_Texture2D[x3d_MaxTextures];
out vec4 c;
void main() { c = texture(x3d_Texture2D[0], vec2(0.5)); }
]]>"""
        scene = load(document(composed(fragment),
                              texture='<PixelTexture image="1 1 3 0x00FF00"/>'))
        assert greenish(centre(scene, renderer, frames=3))

    def test_a_texture_field_is_a_sampler(self, renderer):
        fragment = """<![CDATA[#version 330 core
uniform sampler2D picture;
out vec4 c;
void main() { c = texture(picture, vec2(0.5)); }
]]>"""
        fields = ('<field name="picture" type="SFNode" accessType="inputOutput">'
                  '<PixelTexture image="1 1 3 0x00FF00"/></field>')
        scene = load(document(composed(fragment, fields=fields)))
        assert greenish(centre(scene, renderer, frames=3))

    def test_a_glsl_1_shader_is_translated(self, renderer):
        vertex = '<![CDATA[void main() { gl_Position = ftransform(); }]]>'
        fragment = '<![CDATA[void main() { gl_FragColor = gl_FrontMaterial.diffuse; }]]>'
        scene = load(document(composed(fragment, vertex=vertex),
                              material='<Material diffuseColor="0 1 0"/>'))
        assert greenish(centre(scene, renderer))


@pytest.mark.parametrize('renderer', RENDERERS)
class TestTheFirstThatRunsIsSelected:
    def test_a_language_the_engine_does_not_run_is_passed_over(self, renderer):
        cg = ('<ComposedShader DEF="CG" language="Cg"><ShaderPart type="FRAGMENT">'
              '<![CDATA[float4 main() : COLOR { return 1; }]]></ShaderPart></ComposedShader>')
        scene = load(document(cg + composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))
        assert reddish(centre(scene, renderer))
        assert named(scene, 'CG').isSelected is False
        assert named(scene, 'S').isSelected is True

    def test_a_shader_that_does_not_compile_is_passed_over(self, renderer):
        broken = ('<ComposedShader DEF="BROKEN" language="GLSL"><ShaderPart type="FRAGMENT">'
                  '<![CDATA[#version 330 core\nvoid main() { nonsense; }]]></ShaderPart>'
                  '</ComposedShader>')
        scene = load(document(broken + composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))
        assert reddish(centre(scene, renderer))
        assert named(scene, 'BROKEN').isValid is False
        assert named(scene, 'BROKEN').isSelected is False

    def test_with_no_shader_that_runs_the_material_is_drawn(self, renderer):
        empty = ('<ComposedShader DEF="EMPTY" language="GLSL">'
                 '<ShaderPart/><ShaderPart type="FRAGMENT"/></ComposedShader>')
        scene = load(document(
            empty, material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        assert bluish(centre(scene, renderer))
        assert named(scene, 'EMPTY').isValid is False


def _pixels_differ(a, b):
    return np.abs(a.astype(int) - b.astype(int)).max() > 40


GEOMETRY_STAGE = """<![CDATA[#version 330 core
layout(triangles) in;
layout(triangle_strip, max_vertices = 3) out;
out vec3 tint;
void main() {
    for (int i = 0; i < 3; ++i) {
        gl_Position = gl_in[i].gl_Position;
        tint = vec3(0.0, 1.0, 0.0);
        EmitVertex();
    }
    EndPrimitive();
}
]]>"""

TINTED = """<![CDATA[#version 330 core
in vec3 tint;
out vec4 c;
void main() { c = vec4(tint, 1.0); }
]]>"""


@pytest.mark.parametrize('renderer', RENDERERS)
class TestTheOtherShaders:
    def test_a_geometry_stage_is_linked(self, renderer):
        shader = ('<ComposedShader DEF="S" language="GLSL">'
                  '<ShaderPart type="VERTEX">%s</ShaderPart>'
                  '<ShaderPart type="GEOMETRY">%s</ShaderPart>'
                  '<ShaderPart type="FRAGMENT">%s</ShaderPart></ComposedShader>'
                  % (VERTEX, GEOMETRY_STAGE, TINTED))
        assert greenish(centre(load(document(shader)), renderer))

    def test_a_program_shader_sets_each_programs_fields(self, renderer):
        shader = ('<ProgramShader DEF="S" language="GLSL"><ShaderProgram type="VERTEX">%s'
                  '</ShaderProgram><ShaderProgram type="FRAGMENT">'
                  '<field name="colour" type="SFColor" accessType="inputOutput" value="0 1 0"/>'
                  '%s</ShaderProgram></ProgramShader>' % (VERTEX, FLAT))
        scene = load(document(shader))
        assert greenish(centre(scene, renderer))
        assert named(scene, 'S').isSelected is True

    def test_a_packaged_glsl_shader_holds_both_stages(self, renderer):
        import urllib.parse
        text = ('#version 330 core\n'
                '#ifdef X3D_VERTEX_SHADER\n'
                'in vec4 x3d_Vertex; uniform mat4 x3d_ModelViewMatrix, x3d_ProjectionMatrix;\n'
                'void main() { gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex; }\n'
                '#endif\n#ifdef X3D_FRAGMENT_SHADER\n'
                'uniform vec3 colour; out vec4 c; void main() { c = vec4(colour, 1.0); }\n'
                '#endif\n')
        url = 'data:text/plain,' + urllib.parse.quote(text)
        shader = ('<PackagedShader DEF="S" language="GLSL" url=\'"%s"\'>'
                  '<field name="colour" type="SFColor" accessType="inputOutput" value="0 1 0"/>'
                  '</PackagedShader>' % url)
        assert greenish(centre(load(document(shader)), renderer))

    def test_a_packaged_shader_of_another_language_is_passed_over(self, renderer):
        shader = ('<PackagedShader DEF="FX" language="HLSL" url=\'"effect.fx"\'/>' + composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>'))
        scene = load(document(shader))
        assert reddish(centre(scene, renderer))
        assert named(scene, 'FX').isSelected is False

    def test_a_data_url_part_is_its_text(self, renderer):
        import urllib.parse
        fragment = ('#version 330 core\nout vec4 c;\n'
                    'void main() { c = vec4(0.0, 1.0, 0.0, 1.0); }\n')
        shader = ('<ComposedShader DEF="S" language="GLSL">'
                  '<ShaderPart type="VERTEX">%s</ShaderPart>'
                  '<ShaderPart type="FRAGMENT" url=\'"data:text/plain,%s"\'/></ComposedShader>'
                  % (VERTEX, urllib.parse.quote(fragment)))
        assert greenish(centre(load(document(shader)), renderer))


class TestTessellation:
    TESS = ('<ShaderPart type="TESS_CONTROL"><![CDATA[#version 400 core\n'
            'layout(vertices = 3) out;\n'
            'void main() {\n'
            '    gl_out[gl_InvocationID].gl_Position = gl_in[gl_InvocationID].gl_Position;\n'
            '    gl_TessLevelOuter[0] = 2.0; gl_TessLevelOuter[1] = 2.0;\n'
            '    gl_TessLevelOuter[2] = 2.0; gl_TessLevelInner[0] = 2.0;\n'
            '}]]></ShaderPart>'
            '<ShaderPart type="TESS_EVALUATION"><![CDATA[#version 400 core\n'
            'layout(triangles) in;\n'
            'void main() {\n'
            '    gl_Position = gl_TessCoord.x * gl_in[0].gl_Position\n'
            '        + gl_TessCoord.y * gl_in[1].gl_Position + gl_TessCoord.z * gl_in[2].gl_Position;\n'
            '}]]></ShaderPart>')

    def _shader(self):
        return ('<ComposedShader DEF="S" language="GLSL">'
                '<ShaderPart type="VERTEX">%s</ShaderPart>%s'
                '<ShaderPart type="FRAGMENT"><![CDATA[#version 400 core\nout vec4 c;\n'
                'void main() { c = vec4(0.0, 1.0, 0.0, 1.0); }]]></ShaderPart>'
                '</ComposedShader>' % (VERTEX, self.TESS))

    def test_tessellation_stages_draw_in_a_4_context(self):
        scene = load(document(self._shader(), material='<Material diffuseColor="1 0 0"/>'))
        with scene_context(scene, size=(64, 64), version=(4, 1)) as context:
            pixel = drawn_image(context)[32, 32]
        assert greenish(pixel)
        assert named(scene, 'S').isValid is True

    def test_a_3_3_context_has_no_tessellation_so_the_material_is_drawn(self):
        scene = load(document(
            self._shader(), material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        with scene_context(scene, size=(64, 64), version=(3, 3)) as context:
            pixel = drawn_image(context)[32, 32]
        assert bluish(pixel)
        assert named(scene, 'S').isValid is False


class TestActivate:
    def _scene(self):
        return load(document(composed(
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))

    def test_a_changed_source_waits_for_activate(self):
        scene = self._scene()
        part = named(scene, 'S').parts[1]
        with scene_context(scene, size=(64, 64)) as context:
            assert reddish(drawn_image(context)[32, 32])
            part.sourceCode = ('#version 330 core\nout vec4 c;\n'
                               'void main() { c = vec4(0.0, 1.0, 0.0, 1.0); }\n')
            assert reddish(drawn_image(context)[32, 32])
            named(scene, 'S').activate = True
            assert greenish(drawn_image(context)[32, 32])

    def test_a_source_that_arrives_before_the_first_link_is_used(self):
        scene = load(document(
            '<ComposedShader DEF="S" language="GLSL"><ShaderPart type="VERTEX">%s</ShaderPart>'
            '<ShaderPart DEF="F" type="FRAGMENT"/></ComposedShader>' % VERTEX,
            material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        with scene_context(scene, size=(64, 64)) as context:
            assert bluish(drawn_image(context)[32, 32])
            named(scene, 'F').sourceCode = ('#version 330 core\nout vec4 c;\n'
                                            'void main() { c = vec4(0.0, 1.0, 0.0, 1.0); }\n')
            assert greenish(drawn_image(context)[32, 32])


class TestSourceFiles:
    def _write(self, directory, fragment_url):
        (directory / 'green.frag').write_text(
            '#version 330 core\nout vec4 c;\nvoid main() { c = vec4(0.0, 1.0, 0.0, 1.0); }\n')
        path = directory / 'scene.x3d'
        path.write_text(document(
            '<ComposedShader DEF="S" language="GLSL"><ShaderPart type="VERTEX">%s</ShaderPart>'
            '<ShaderPart DEF="F" type="FRAGMENT" url=\'"%s"\'/></ComposedShader>'
            % (VERTEX, fragment_url),
            material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        return path

    def _draw(self, path):
        from OpenGLContext.loaders.loader import Loader
        scene = Loader.load(str(path))
        background.wait_for_idle()
        with scene_context(scene, size=(64, 64)) as context:
            drawn_image(context)
            background.wait_for_idle()
            return scene, drawn_image(context)[32, 32]

    def test_a_part_reads_a_file_beside_its_document(self, tmp_path):
        scene, pixel = self._draw(self._write(tmp_path, 'green.frag'))
        assert greenish(pixel)

    def test_a_part_naming_a_file_outside_its_directory_is_not_read(self, tmp_path):
        inner = tmp_path / 'inner'
        inner.mkdir()
        self._write(tmp_path, 'green.frag')
        path = self._write(inner, '../green.frag')
        (inner / 'green.frag').unlink()
        scene, pixel = self._draw(path)
        assert bluish(pixel)
        assert named(scene, 'S').isValid is False
