"""The geometry stage that sends one draw to several views, and the table it reads.

One submission reaches every view through a geometry shader that emits each
triangle once per view. It is generated from the vertex shader it follows, so
the two cannot disagree about what passes between them; the table of views it
reads is packed on the CPU in the std140 layout the shader declares.
"""
import numpy as np
import pytest

from OpenGLContext.multiview import strategy as multiview
from OpenGLContext.passes import shadersource


PBR_VERTEX = shadersource.preprocess_shader('pbr.vert', ['#define PBR_SKINNING 1'])
LIT_VERTEX = shadersource.preprocess_shader('vrml97_lighting.vert')


class TestWhatTheVertexStageHandsOn:
    def test_every_output_is_found_with_its_type(self):
        found = {v.name: v for v in shadersource.vertex_outputs(LIT_VERTEX)}
        assert set(found) == {'vNormal', 'vPosition', 'vTexCoord', 'vObjectId'}
        assert found['vNormal'].type == 'vec3'
        assert found['vObjectId'].flat and not found['vNormal'].flat

    def test_the_pbr_outputs_include_the_eye_position(self):
        names = [v.name for v in shadersource.vertex_outputs(PBR_VERTEX)]
        assert 'vPosition' in names and 'vMaterialIndex' in names

    def test_several_outputs_declared_on_one_line_are_each_found(self):
        source = ('#version 330 core\n'
                  'out vec2 vUV; out vec3 vEyePos; flat out int vKind;\n'
                  'out float vH;\n')
        found = {v.name: v for v in shadersource.vertex_outputs(source)}
        assert set(found) == {'vUV', 'vEyePos', 'vKind', 'vH'}
        assert found['vKind'].flat and found['vEyePos'].type == 'vec3'

    def test_each_output_is_renamed_for_the_geometry_stage_to_read(self):
        defines = shadersource.geometry_input_defines(LIT_VERTEX)
        assert '#define vNormal gs_vNormal' in defines
        assert len(defines) == 4


class TestTheVertexRouting:
    def test_the_routing_is_compiled_in_at_410_with_its_extension(self):
        source = shadersource.vertex_routing_source(
            LIT_VERTEX, 4, 'GL_ARB_shader_viewport_layer_array')
        assert source.startswith('#version 410 core')
        assert '#extension GL_ARB_shader_viewport_layer_array : require' in source
        assert '#define MULTIVIEW_VERTEX 1' in source
        assert 'routeToView(vPosition);' in source

    def test_the_routings_own_output_is_not_handed_to_a_geometry_stage(self):
        names = [v.name for v in shadersource.vertex_outputs(LIT_VERTEX)]
        assert 'vView' not in names

    def test_each_view_in_a_mask_is_listed_once(self):
        count, indices = multiview.view_list(0b1010)
        assert count == 2
        assert indices[:2] == [1, 3]
        assert len(indices) == multiview.MAX_VIEWS


class TestTheGeometryStage:
    def source(self, views=4, version=(4, 6)):
        return shadersource.geometry_stage_source(LIT_VERTEX, views, version)

    def test_one_invocation_per_view_and_a_triangle_each(self):
        source = self.source(views=3)
        assert 'invocations = 3' in source
        assert 'max_vertices = 3' in source
        assert 'gl_ViewportIndex' in source

    def test_a_41_driver_needs_no_extension(self):
        assert '#version 410 core' in self.source(version=(4, 1))
        assert '#extension' not in self.source(version=(4, 1))

    def test_a_40_driver_asks_for_viewport_arrays(self):
        source = self.source(version=(4, 0))
        assert '#version 400 core' in source
        assert '#extension GL_ARB_viewport_array : require' in source

    def test_an_older_driver_asks_for_instanced_geometry_shaders_too(self):
        source = self.source(version=(3, 3))
        assert '#version 330 core' in source
        assert '#extension GL_ARB_gpu_shader5 : require' in source

    def test_every_output_is_passed_on_under_its_own_name(self):
        source = self.source()
        for name in ('vNormal', 'vPosition', 'vTexCoord', 'vObjectId'):
            assert '%s = gs_%s[i];' % (name, name) in source

    def test_the_views_must_fit_the_table(self):
        with pytest.raises(ValueError):
            self.source(views=multiview.MAX_VIEWS + 1)
        with pytest.raises(ValueError):
            self.source(views=1)


def _platform(position, look=(0.0, 0.0, 0.0), ortho=None):
    from OpenGLContext.move.followcam import look_at_orientation
    from OpenGLContext.move.viewplatform import ViewPlatform
    return ViewPlatform(position=position,
                        orientation=look_at_orientation(position, look))


def _frame(camera, rect):
    from OpenGLContext.multiview.views import View
    view = View(camera)
    view.rect = rect
    model = np.asarray(camera.modelMatrix(), 'f')
    projection = np.asarray(camera.viewMatrix(), 'f')
    return multiview.ViewFrame(view, camera, rect, model, projection,
                               model @ projection, None)


class TestTheViewTable:
    def frames(self):
        return [_frame(_platform((0.0, 2.0, 10.0)), (0, 0, 100, 100)),
                _frame(_platform((8.0, 3.0, -4.0)), (100, 0, 100, 100))]

    def test_it_is_one_record_per_view_in_std140(self):
        frames = self.frames()
        data = multiview.pack_view_table(frames, frames[0])
        assert len(data) == 2 * multiview.VIEW_RECORD_BYTES

    def test_the_reference_view_projects_its_own_eye_space_directly(self):
        frames = self.frames()
        records = multiview.view_records(frames, frames[0])
        assert np.allclose(records[0].refToClip, frames[0].projection, atol=1e-5)
        assert np.allclose(records[0].eye, (0.0, 0.0, 0.0, 1.0), atol=1e-5)

    def test_another_view_sees_a_point_where_its_own_camera_would(self):
        frames = self.frames()
        records = multiview.view_records(frames, frames[0])
        world = np.array([1.0, 0.5, -2.0, 1.0])
        in_reference = world @ np.asarray(frames[0].modelView, 'd')
        through_table = in_reference @ np.asarray(records[1].refToClip, 'd')
        directly = world @ np.asarray(frames[1].modelproj, 'd')
        assert np.allclose(through_table / through_table[3],
                           directly / directly[3], atol=1e-4)

    def test_another_views_eye_is_its_camera_in_reference_space(self):
        frames = self.frames()
        records = multiview.view_records(frames, frames[0])
        camera = np.array([8.0, 3.0, -4.0, 1.0]) @ np.asarray(frames[0].modelView, 'd')
        assert np.allclose(records[1].eye, camera, atol=1e-4)

    def test_only_the_fitted_view_reads_the_cascades_by_depth(self):
        frames = self.frames()
        frames[0].fitted = True
        records = multiview.view_records(frames, frames[0])
        assert records[0].cascadeByFit == 0
        assert records[1].cascadeByFit == 1

    def test_which_views_a_record_is_drawn_in_is_a_mask(self):
        assert multiview.view_mask([0, 2, 3]) == 0b1101
        assert multiview.view_mask([]) == 0


class TestOnTheDriver:
    @pytest.fixture
    def programs(self, gl_context):
        found = multiview.MultiviewCapabilities.detect()
        if 'geometry' not in found.available():
            pytest.skip('this driver has no viewport arrays')
        return found

    def test_the_lit_programs_link_with_the_geometry_stage(self, programs):
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        shader = VRML97ShaderProgram()
        assert shader.compile()
        assert shader.select_program_set(4)
        assert shader.program and shader.vertex_color_program
        shader.select_program_set(0)

    def test_the_pbr_program_links_with_the_geometry_stage(self, programs):
        from OpenGLContext.passes.pbrpass import PBRShaderProgram
        shader = PBRShaderProgram()
        assert shader.compile()
        plain = shader.program
        assert shader.select_program_set(2)
        assert shader.program != plain
        shader.select_program_set(0)
        assert shader.program == plain

    def test_the_lit_programs_link_with_the_vertex_routing(self, gl_context):
        from OpenGLContext.passes.pbrpass import PBRShaderProgram
        multiview.reset_detected()
        if 'vertex' not in multiview.MultiviewCapabilities.detect().available():
            pytest.skip('this driver has no vertex-stage viewport index')
        shader = PBRShaderProgram()
        assert shader.compile()
        assert shader.select_program_set(4, 'vertex')
        assert shader.program_strategy == 'vertex'
        shader.select_program_set(0)
        assert shader.program_strategy == ''

    def test_the_table_layout_is_the_drivers(self, programs):
        from OpenGL import GL
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        shader = VRML97ShaderProgram()
        assert shader.compile() and shader.select_program_set(3)
        offsets = multiview.driver_view_offsets(shader.program)
        assert offsets == multiview.view_record_offsets(3)
        size = np.zeros(1, 'i')
        GL.glGetActiveUniformBlockiv(
            shader.program,
            GL.glGetUniformBlockIndex(shader.program, 'ViewBlock'),
            GL.GL_UNIFORM_BLOCK_DATA_SIZE, size)
        assert int(size[0]) == 3 * multiview.VIEW_RECORD_BYTES
        shader.select_program_set(0)
