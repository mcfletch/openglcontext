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

    def test_a_context_with_no_tessellation_draws_the_material(self, monkeypatch):
        """A driver without the stage answers GL_INVALID_ENUM for its shaders"""
        from OpenGLContext.scenegraph import x3dshaders
        monkeypatch.setitem(x3dshaders.GL_STAGES, 'TESS_CONTROL', 0x1234)
        scene = load(document(
            self._shader(), material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        with scene_context(scene, size=(64, 64), version=(4, 1)) as context:
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


ATTRIBUTE_VERTEX = """<![CDATA[#version 330 core
in vec4 x3d_Vertex;
in vec3 heat;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
out vec3 tint;
void main() {
    tint = heat;
    gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex;
}
]]>"""

MATRIX_VERTEX = """<![CDATA[#version 330 core
in vec4 x3d_Vertex;
in mat4 frame;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
out vec3 tint;
void main() {
    tint = frame[1].xyz;
    gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex;
}
]]>"""

QUAD = '-2 -2 0 2 -2 0 2 2 0 -2 2 0'
GREEN_HEAT = ('<FloatVertexAttribute name="heat" numComponents="3" '
              'value="0 1 0 0 1 0 0 1 0 0 1 0"/>')
# Column 1 of each matrix is green; X3D gives a matrix's values column by column.
GREEN_FRAME = ('<Matrix4VertexAttribute name="frame" value="%s"/>'
               % ' '.join(['0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0'] * 4))
GEOMETRIES = {
    'IndexedFaceSet': ('<IndexedFaceSet solid="false" coordIndex="0 1 2 3 -1">'
                       '<Coordinate point="%s"/>%%s</IndexedFaceSet>' % QUAD),
    'IndexedTriangleSet': ('<IndexedTriangleSet solid="false" index="0 1 2 0 2 3">'
                           '<Coordinate point="%s"/>%%s</IndexedTriangleSet>' % QUAD),
    'TriangleSet (normal per face)': (
        '<IndexedTriangleSet solid="false" index="0 1 2 0 2 3" normalPerVertex="false">'
        '<Coordinate point="%s"/><Normal vector="0 0 1 0 0 1"/>%%s</IndexedTriangleSet>' % QUAD),
    'ElevationGrid': ('<Transform rotation="1 0 0 -1.5708" translation="-2 -2 0">'
                      '<Shape><Appearance>%(look)s</Appearance><ElevationGrid solid="false" '
                      'xDimension="2" zDimension="2" xSpacing="4" zSpacing="4" height="0 0 0 0">'
                      '%%s</ElevationGrid></Shape></Transform>'),
}


def _attribute_scene(geometry, attribute, vertex):
    shader = ('<ComposedShader language="GLSL"><ShaderPart type="VERTEX">%s</ShaderPart>'
              '<ShaderPart type="FRAGMENT">%s</ShaderPart></ComposedShader>' % (vertex, TINTED))
    if geometry.startswith('<Transform'):
        body = geometry % {'look': shader}
        return load('<X3D profile="Full" version="4.0"><Scene>'
                    '<Viewpoint position="0 0 10"/>%s</Scene></X3D>' % (body % attribute,))
    return load(document(shader, geometry=geometry % attribute))


@pytest.mark.parametrize('renderer', RENDERERS)
@pytest.mark.parametrize('geometry', sorted(GEOMETRIES))
class TestVertexAttributes:
    def test_a_float_attribute_is_the_input_of_its_name(self, renderer, geometry):
        scene = _attribute_scene(GEOMETRIES[geometry], GREEN_HEAT, ATTRIBUTE_VERTEX)
        assert greenish(centre(scene, renderer))

    def test_a_matrix_attribute_takes_a_location_a_column(self, renderer, geometry):
        scene = _attribute_scene(GEOMETRIES[geometry], GREEN_FRAME, MATRIX_VERTEX)
        assert greenish(centre(scene, renderer))


#: Clicks the middle of a document's frame; exits 0 where the click reached the
#: shape named SHAPE, the way an application's pointer does.
PICK_DRIVER = r'''
import os, sys
try:
    import glfw
    from vrml import x3d as vrml_x3d, protofunctions
    from OpenGLContext.context import Context as Base
    from OpenGLContext.events.mouseevents import MouseButtonEvent
    from OpenGLContext.loaders.x3d import prototypes
    scene = vrml_x3d.loads(sys.argv[1], prototypes=prototypes())
    target = scene.getDEF('SHAPE')
    hits = []

    class C(Base):
        def OnInit(self):
            self.sg = scene
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=self.hit)

        def hit(self, event):
            paths = event.getObjectPaths()
            hits.append(bool(paths and paths[0] and paths[0][-1] is target))

    inst = C()
    inst.deferRedraw = True
    w, h = inst.getViewPort()
    for i in range(16):
        glfw.poll_events()
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            inst.addPickEvent(ev); inst.triggerPick()
        inst.OnDraw(force=1)
    inst.flushPendingPicks()
    sys.stderr.write('HITS=%r\n' % (hits,))
    os._exit(0 if hits and all(hits) else 2)
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    from OpenGLContext.testing.plugin import NO_CONTEXT_STATUS
    os._exit(NO_CONTEXT_STATUS)
'''


@pytest.mark.parametrize('renderer', RENDERERS)
class TestThePassAroundTheShader:
    def test_a_shape_drawn_by_its_shader_is_picked(self, renderer):
        """The fragment stage writes the pass's object id beside the colour"""
        import os
        import subprocess
        import sys
        from OpenGLContext.testing.plugin import skip_if_child_had_no_context
        environment = dict(os.environ, OPENGLCONTEXT_RENDERER=renderer,
                           OPENGLCONTEXT_PROFILE='core', OPENGLCONTEXT_SHADOWS='0',
                           OPENGLCONTEXT_DISABLE_FPS_DISPLAY='1')
        process = subprocess.run(
            [sys.executable, '-c', PICK_DRIVER, document(composed(fields=(
                '<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>')))],
            capture_output=True, text=True, timeout=120, env=environment)
        skip_if_child_had_no_context(process.returncode, process.stderr)
        assert process.returncode == 0, process.stderr

    def test_the_next_shape_has_its_own_texture_back(self, renderer):
        """The shader's samplers take units the pass binds a material's maps on"""
        fragment = """<![CDATA[#version 330 core
uniform sampler2D x3d_Texture2D[x3d_MaxTextures];
uniform sampler2D a, b, d;
out vec4 c;
void main() {
    // a, b and d are given no texture, and read black.
    c = vec4(texture(x3d_Texture2D[0], vec2(0.5)).rgb + texture(a, vec2(0.5)).rgb
             + texture(b, vec2(0.5)).rgb + texture(d, vec2(0.5)).rgb, 1.0);
}
]]>"""
        # Drawn front to back: a textured box, the shader's, the same look again.
        textured = ('<Shape><Appearance DEF="LOOK"><PixelTexture image="1 1 3 0xFF0000"/>'
                    '</Appearance><Box size="1.5 1.5 1.5"/></Shape>')
        scene = load(
            '<X3D profile="Full" version="4.0"><Scene>'
            '<Viewpoint position="0 0 10"/><NavigationInfo headlight="false"/>'
            '<Transform translation="-2.5 0 1">%s</Transform>'
            '<Transform translation="0 0 0"><Shape><Appearance>'
            '<PixelTexture image="1 1 3 0x00FF00"/>%s</Appearance>'
            '<Box size="1.5 1.5 1.5"/></Shape></Transform>'
            '<Transform translation="2.5 0 -1"><Shape><Appearance USE="LOOK"/>'
            '<Box size="1.5 1.5 1.5"/></Shape></Transform>'
            '</Scene></X3D>' % (textured, composed(fragment)))
        with scene_context(scene, size=(96, 64),
                           environment={'OPENGLCONTEXT_RENDERER': renderer}) as context:
            for _ in range(3):
                image = drawn_image(context)
        left, middle, right = image[32, 29], image[32, 48], image[32, 67]
        assert reddish(left), left
        assert greenish(middle), middle
        assert reddish(right), right


class _Mode:
    """What a shader's draw reads of the pass: matrices, the viewport, a cache"""

    shader_program = None

    def __init__(self):
        from vrml import cache
        self.cache = cache.Cache()
        self.matrix = np.identity(4, dtype='f')
        self.projection = np.identity(4, dtype='f')

    def getViewport(self):
        return (0, 0, 64, 64)


@pytest.mark.usefixtures('gl_context')
class TestTheDrawPutsThingsBack:
    def test_the_units_its_samplers_took_are_bound_as_they_were(self):
        from OpenGL import GL
        from OpenGLContext.scenegraph import x3dshaders
        fragment = ('#version 330 core\nuniform sampler2D a, b, c, d;\nout vec4 o;\n'
                    'void main() { o = texture(a, vec2(0.5)) + texture(b, vec2(0.5))'
                    ' + texture(c, vec2(0.5)) + texture(d, vec2(0.5)); }\n')
        vertex = '#version 330 core\nin vec4 x3d_Vertex;\nvoid main() { gl_Position = x3d_Vertex; }\n'
        linked = x3dshaders.link([('VERTEX', vertex), ('FRAGMENT', fragment)], (), 8)
        shader = x3dshaders.ComposedShader()
        names = [int(name) for name in GL.glGenTextures(4)]
        try:
            for unit, name in enumerate(names):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, name)
            drawn = x3dshaders.X3DShaderDraw(linked, shader, _Mode(), None)
            drawn.begin()
            during = []
            for unit in range(4):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                during.append(int(GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D)))
            drawn.end()
            after = []
            for unit in range(4):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                after.append(int(GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D)))
        finally:
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glDeleteTextures(names)
            GL.glUseProgram(0)
            x3dshaders.delete_program(linked.program)
        assert during == [0, 0, 0, 0]
        assert after == names


class TestTheMemosFollowTheirInputs:
    def test_a_shaders_values_follow_every_field_it_declares(self):
        from OpenGLContext.scenegraph import x3dshaders
        from OpenGLContext.testing.memo import check_memo_inputs
        scene = load(document(composed(fields=(
            '<field name="colour" type="SFColor" accessType="inputOutput" value="1 0 0"/>'
            '<field name="scale" type="SFFloat" accessType="initializeOnly" value="1"/>'
            '<field name="pulse" type="SFTime" accessType="inputOnly"/>'
            '<field name="picture" type="SFNode" accessType="inputOutput"/>'))))
        shader = named(scene, 'S')

        def answer(values):
            uniforms, textures = values
            return (tuple((name, tuple(found.values.tolist())) for name, found in uniforms),
                    tuple((name, id(texture)) for name, texture in textures))

        def fresh():
            return answer(x3dshaders.field_values(shader))

        picture = vrml_x3d.nodes.PixelTexture()
        check_memo_inputs(lambda: answer(x3dshaders.user_values(shader)), [
            ('colour', lambda: setattr(shader, 'colour', (0, 1, 0))),
            ('scale', lambda: setattr(shader, 'scale', 2.0)),
            ('pulse, an event', lambda: setattr(shader, 'pulse', 3.0)),
            ('picture', lambda: setattr(shader, 'picture', picture)),
        ], fresh=fresh)

    @pytest.mark.parametrize('geometry', ['IndexedTriangleSet', 'ElevationGrid'])
    def test_a_meshs_vertex_attributes_follow_their_nodes(self, geometry):
        from vrml.x3d import nodes as x3d
        from OpenGLContext.loaders.x3d import prototypes
        from OpenGLContext.testing.memo import check_memo_inputs
        built = prototypes()
        heat = x3d.FloatVertexAttribute(name='heat', numComponents=1, value=[0, 1, 2, 3])
        if geometry == 'ElevationGrid':
            node = built['ElevationGrid'](xDimension=2, zDimension=2, height=[0, 0, 0, 0],
                                          attrib=[heat])
        else:
            node = built['IndexedTriangleSet'](
                index=[0, 1, 2, 0, 2, 3], attrib=[heat],
                coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))

        def answer(mesh):
            return tuple((name, values.tolist()) for name, values, _ in mesh.vertex_attributes)

        def fresh():
            return answer(node.buildMesh())

        check_memo_inputs(lambda: answer(node.mesh()), [
            ('attrib.value', lambda: setattr(heat, 'value', [3, 2, 1, 0])),
            ('attrib.name', lambda: setattr(heat, 'name', 'cold')),
            ('attrib.numComponents', lambda: (setattr(heat, 'numComponents', 2),
                                              setattr(heat, 'value', list(range(8))))),
            ('geometry.attrib', lambda: setattr(node, 'attrib', [])),
        ], fresh=fresh)

    def test_a_face_sets_compiled_attributes_follow_their_nodes(self):
        from vrml.x3d import nodes as x3d
        from OpenGLContext.scenegraph.basenodes import Coordinate, IndexedFaceSet
        from OpenGLContext.scenegraph.ifscompiler import ArrayGeometryCompiler
        from OpenGLContext.testing.memo import check_memo_inputs
        heat = x3d.FloatVertexAttribute(name='heat', numComponents=1, value=[0, 1, 2, 3])
        node = IndexedFaceSet(coordIndex=[0, 1, 2, 3, -1], attrib=[heat], coord=Coordinate(
            point=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))
        mode = _Mode()

        def answer(renderer):
            return tuple((entry.name, entry.buffer.data.tolist()) for entry in renderer.named)

        def ask():
            renderer = mode.cache.getData(node)
            if renderer is None:
                renderer = node.compile(mode=mode)
            return answer(renderer)

        check_memo_inputs(ask, [
            ('attrib.value', lambda: setattr(heat, 'value', [3, 2, 1, 0])),
            ('attrib.name', lambda: setattr(heat, 'name', 'cold')),
            ('geometry.attrib', lambda: setattr(node, 'attrib', [])),
        ], fresh=lambda: answer(ArrayGeometryCompiler(node).compile(mode=mode)))


@pytest.mark.parametrize('renderer', RENDERERS)
def test_shapes_sharing_a_shader_and_geometry_are_each_drawn_by_it(renderer):
    """Shapes the pass would draw as one instanced group are drawn by their shader"""
    shader = composed(
        fields='<field name="colour" type="SFColor" accessType="inputOutput" value="0 1 0"/>')
    boxes = ''.join(
        '<Transform translation="%d 0 0"><Shape>%s<Box %s size="0.8 0.8 0.8"/></Shape></Transform>'
        % (x, '<Appearance DEF="LOOK"><Material diffuseColor="1 0 0" emissiveColor="1 0 0"/>%s'
              '</Appearance>' % shader if x == -3 else '<Appearance USE="LOOK"/>',
           'DEF="BOX"' if x == -3 else '')
        for x in range(-3, 4))
    boxes = boxes.replace('<Box  size="0.8 0.8 0.8"/>', '<Box USE="BOX"/>')
    scene = load('<X3D profile="Full" version="4.0"><Scene><Viewpoint position="0 0 10"/>'
                 '<NavigationInfo headlight="false"/>%s</Scene></X3D>' % boxes)
    with scene_context(scene, size=(128, 64),
                       environment={'OPENGLCONTEXT_RENDERER': renderer,
                                    'OPENGLCONTEXT_INSTANCING': '1'}) as context:
        image = drawn_image(context)
    row = image[32]
    lit = [pixel for pixel in row if pixel.max() > 100]
    assert lit and all(greenish(pixel.astype(int)) for pixel in lit)


def test_the_batching_memo_follows_an_appearances_shaders(monkeypatch):
    """A shape whose appearance lists shaders is drawn alone, not in a group"""
    from OpenGLContext.passes.pbrpass import PBRPass, instance_collapse_is_enabled
    from OpenGLContext.scenegraph import basenodes, x3dshaders
    from OpenGLContext.testing.memo import check_memo_inputs
    monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', raising=False)
    passing = PBRPass.__new__(PBRPass)
    from tests.unit.test_memo_inputs import _mesh
    shape = basenodes.Shape(geometry=_mesh(),
                            appearance=basenodes.Appearance(material=basenodes.Material()))

    def ask():
        key, instanceable = passing.batchers()
        return key(shape), instanceable(shape)

    def fresh():
        key = passing._keyFor(shape, instance_collapse_is_enabled())  # noqa: SLF001 the batching memo's key, which this test holds to its inputs
        return key, key is not None and bool(passing._instanceable(shape))  # noqa: SLF001 the batching memo's key, which this test holds to its inputs

    check_memo_inputs(ask, [
        ('appearance.shaders', lambda: setattr(
            shape.appearance, 'shaders', [x3dshaders.ComposedShader()])),
        ('appearance.shaders, cleared', lambda: setattr(shape.appearance, 'shaders', [])),
    ], fresh=fresh)


@pytest.fixture
def compatibility():
    refused = profile_unavailable('compatibility')
    if refused:
        pytest.skip(refused)
    return {'OPENGLCONTEXT_PROFILE': 'compatibility'}


class TestTheCompatibilityProfile:
    """GLSL 1.x reads the fixed-function state the compatibility pass sets"""

    def _centre(self, scene, environment):
        with scene_context(scene, size=(64, 64), environment=environment) as context:
            drawn_image(context)
            return drawn_image(context)[32, 32].astype(int)

    def test_a_glsl_1_shader_runs_as_written(self, compatibility):
        vertex = '<![CDATA[void main() { gl_Position = ftransform(); }]]>'
        fragment = ('<![CDATA[uniform vec3 colour;\n'
                    'void main() { gl_FragColor = vec4(colour, 1.0) * gl_FrontMaterial.diffuse; }]]>')
        scene = load(document(composed(
            fragment, vertex=vertex,
            fields='<field name="colour" type="SFColor" accessType="inputOutput" value="0 1 0"/>'),
            material='<Material diffuseColor="1 1 1"/>'))
        assert greenish(self._centre(scene, compatibility))
        assert named(scene, 'S').isSelected is True

    def test_a_shader_of_x3d_names_is_passed_over_for_the_material(self, compatibility):
        scene = load(document(
            composed(fields='<field name="colour" type="SFColor" accessType="inputOutput" '
                     'value="0 1 0"/>'),
            material='<Material diffuseColor="0 0 1" emissiveColor="0 0 1"/>'))
        assert bluish(self._centre(scene, compatibility))
        assert named(scene, 'S').isSelected is False


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_shader_built_in_code_declares_its_fields(renderer):
    """What a document's <field> does, from Python"""
    from OpenGLContext.scenegraph import basenodes, x3dshaders
    from OpenGLContext.scenegraph.x3dshaders import ComposedShader, ShaderPart
    strip = lambda text: text.replace('<![CDATA[', '').replace(']]>', '')  # noqa: E731 a one-line helper
    shader = ComposedShader(language='GLSL', parts=[
        ShaderPart(type='VERTEX', sourceCode=strip(VERTEX)),
        ShaderPart(type='FRAGMENT', sourceCode=strip(FLAT))])
    x3dshaders.declare_field(shader, 'colour', 'SFColor', (1, 0, 0))
    assert shader.colour.tolist() == [1, 0, 0]
    shape = basenodes.Shape(geometry=basenodes.Box(size=(4, 4, 4)),
                            appearance=basenodes.Appearance(shaders=[shader]))
    scene = [basenodes.Viewpoint(position=(0, 0, 10)), shape]
    assert reddish(centre(scene, renderer))
    shader.colour = (0, 1, 0)
    assert greenish(centre(scene, renderer))


NORMAL_SHADED = """#version 330 core
in vec3 normal;
out vec4 c;
void main() { c = vec4(vec3(0.2, 0.6, 1.0) * max(normalize(normal).z, 0.0), 1.0); }
"""

NORMAL_VERTEX = """#version 330 core
in vec4 x3d_Vertex;
in vec3 x3d_Normal;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
uniform mat3 x3d_NormalMatrix;
out vec3 normal;
void main() {
    normal = x3d_NormalMatrix * x3d_Normal;
    gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex;
}
"""


@pytest.mark.parametrize('renderer', RENDERERS)
@pytest.mark.parametrize('geometry', ['Box', 'Sphere', 'IndexedTriangleSet'])
def test_a_shader_drawn_shape_mirrors(renderer, geometry):
    """Under a mirroring transform the shape shows its outside, lit as its mirror image"""
    from OpenGLContext.loaders.x3d import prototypes
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.x3dshaders import ComposedShader, ShaderPart
    from OpenGLContext.testing.mirrored import check_mirrored_render
    from vrml.x3d import nodes as x3d
    made = {
        'Box': lambda: basenodes.Box(size=(1.5, 1, 1)),
        'Sphere': lambda: basenodes.Sphere(),
        'IndexedTriangleSet': lambda: prototypes()['IndexedTriangleSet'](
            index=[0, 1, 2], coord=x3d.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (0.5, 1, 0)])),
    }[geometry]()
    shader = ComposedShader(language='GLSL', parts=[
        ShaderPart(type='VERTEX', sourceCode=NORMAL_VERTEX),
        ShaderPart(type='FRAGMENT', sourceCode=NORMAL_SHADED)])
    check_mirrored_render(made, appearance=basenodes.Appearance(shaders=[shader]),
                          environment={'OPENGLCONTEXT_RENDERER': renderer})


@pytest.mark.parametrize('renderer', RENDERERS)
@pytest.mark.parametrize('geometry', ['IndexedFaceSet', 'IndexedTriangleSet'])
def test_a_short_attribute_does_not_move_the_others(renderer, geometry):
    """One with fewer values than coordinates reads zero past them; the next is where it was"""
    short = '<FloatVertexAttribute name="cold" numComponents="4" value="1 1 1 1"/>'
    vertex = ATTRIBUTE_VERTEX.replace('in vec3 heat;', 'in vec4 cold;\nin vec3 heat;').replace(
        'tint = heat;', 'tint = heat + cold.xyz * 0.0;')
    scene = _attribute_scene(GEOMETRIES[geometry], short + GREEN_HEAT, vertex)
    assert greenish(centre(scene, renderer))
