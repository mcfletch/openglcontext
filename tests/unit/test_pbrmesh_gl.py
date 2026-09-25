"""In-process GL tests for PBRMesh's GPU upload + draw path (_MeshGPU).

The subprocess PBR capture tests render whole scenes but collect no in-process
coverage, so the VAO/VBO build, the indexed/array/points draw arms, the
morph/skin dynamic re-upload and the pending-VAO-delete queue are exercised here
directly against a hidden core-profile GLFW context.
"""
import gc
import types

import numpy as np
import pytest

from vrml.cache import Cache
from OpenGL.GL import GL_CCW, GL_NO_ERROR, GL_POINTS, GL_TRIANGLES, glGetError
from OpenGL import GL

from OpenGLContext.scenegraph.pbrmesh import PBRMesh, _MeshGPU
from OpenGLContext.passes import instancing
from OpenGLContext.scenegraph.basenodes import Shape
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


@pytest.fixture
def gl(gl_window):
    return gl_window('pbrmesh', forward_compatible=True)


def _mode(**over):
    m = types.SimpleNamespace(
        cache=Cache(), shader_mode=True, matrix=np.eye(4, dtype='f'),
        shadow_pass=False, shader_program=None, context=types.SimpleNamespace())
    for k, v in over.items():
        setattr(m, k, v)
    return m


def _full_mesh(indices=(0, 1, 2), draw_mode=GL_TRIANGLES):
    """A mesh carrying every optional attribute so all six VBOs build."""
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
    return PBRMesh(
        positions=p,
        normals=np.tile([0, 0, 1], (3, 1)).astype('f'),
        texcoords=np.array([[0, 0], [1, 0], [0, 1]], 'f'),
        texcoords1=np.array([[0, 0], [0.5, 0], [0, 0.5]], 'f'),
        tangents=np.tile([1, 0, 0, 1], (3, 1)).astype('f'),
        colors=np.tile([1, 1, 1, 1], (3, 1)).astype('f'),
        indices=None if indices is None else np.array(indices, np.uint32),
        draw_mode=draw_mode)


class TestMeshGPUUpload:
    @pytest.mark.usefixtures('gl')
    def test_indexed_mesh_builds_all_attribute_buffers(self):
        mesh = _full_mesh()
        gpu = mesh._gpu(_mode())
        assert gpu.vao != 0
        assert gpu.indexed is True
        assert gpu.count == 3
        assert len(gpu.attr_layout) == 6          # all six optional attrs present
        # Nothing moves this mesh's vertices, so none of its buffers is dynamic:
        # a static mesh should not be carrying the machinery for a re-upload it
        # will never make.
        assert set(gpu.dyn) == set()
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_non_indexed_mesh_counts_vertices(self):
        gpu = _full_mesh(indices=None)._gpu(_mode())
        assert gpu.indexed is False
        assert gpu.count == 3                       # vertex count, not index count
        assert gpu.idx_vbo is None

    @pytest.mark.usefixtures('gl')
    def test_gpu_is_cached_per_context(self):
        mesh = _full_mesh()
        mode = _mode()
        assert mesh._gpu(mode) is mesh._gpu(mode)   # second call reuses the VAO


class TestRenderDraw:
    @pytest.mark.usefixtures('gl')
    def test_render_indexed_triangles(self):
        assert _full_mesh().render(mode=_mode()) == 1

    @pytest.mark.usefixtures('gl')
    def test_render_non_indexed_array(self):
        assert _full_mesh(indices=None).render(mode=_mode()) == 1

    @pytest.mark.usefixtures('gl')
    def test_render_points_mode(self):
        # GL_POINTS enables GL_PROGRAM_POINT_SIZE around the draw.
        assert _full_mesh(draw_mode=GL_POINTS).render(mode=_mode()) == 1

    @pytest.mark.usefixtures('gl')
    def test_render_skips_empty_mesh(self):
        empty = PBRMesh(positions=np.zeros((0, 3), 'f'))
        assert empty.render(mode=_mode()) == 1

    @pytest.mark.usefixtures('gl')
    def test_render_sets_vertex_color_uniform(self):
        calls = []

        class _SP:
            def set_vertex_color(self, flag):
                calls.append(flag)

        _full_mesh().render(mode=_mode(shader_program=_SP()))
        assert calls == [True]                       # mesh has colors


class TestDynamicDeform:
    def _morph_mesh(self):
        p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
        return PBRMesh(
            positions=p,
            normals=np.tile([0, 0, 1], (3, 1)).astype('f'),
            tangents=np.tile([1, 0, 0, 1], (3, 1)).astype('f'),
            morph_targets=[{'positions': np.tile([0, 0, 1], (3, 1)).astype('f'),
                            'normals': np.zeros((3, 3), 'f'),
                            'tangents': np.zeros((3, 3), 'f')}])

    @pytest.mark.usefixtures('gl')
    def test_morph_reupload_on_weight_change(self):
        mesh = self._morph_mesh()
        mode = _mode()
        gpu = mesh._gpu(mode)
        v0 = gpu._uploaded_morph_version
        mesh.set_morph_weights([1.0])                # deforms +z, bumps version
        assert mesh.positions[0][2] == pytest.approx(1.0)
        gpu2 = mesh._gpu(mode)                        # same object, re-uploaded
        assert gpu2 is gpu
        assert gpu2._uploaded_morph_version != v0
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_zero_weight_morph_target_is_skipped(self):
        # Two targets, only the first active: the zero-weight target is skipped in
        # the deform accumulation but the active one still applies.
        p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
        mesh = PBRMesh(
            positions=p,
            morph_targets=[{'positions': np.tile([0, 0, 2], (3, 1)).astype('f')},
                           {'positions': np.tile([0, 0, 9], (3, 1)).astype('f')}])
        mesh.set_morph_weights([1.0, 0.0])           # second weight 0 -> skipped
        assert mesh.positions[0][2] == pytest.approx(2.0)   # only target 0 applied

    def _skinned(self):
        return PBRMesh(
            positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f'),
            normals=np.tile([0, 0, 1], (3, 1)).astype('f'),
            tangents=np.tile([1, 0, 0, 1], (3, 1)).astype('f'),
            skin_joints=np.zeros((3, 4), np.uint32),
            skin_weights=np.tile([1, 0, 0, 0], (3, 1)).astype('f'))

    @staticmethod
    def _shift_x(distance):
        translate = np.eye(4)
        translate[3, 0] = distance                   # row-vector translation +x
        return np.stack([translate])

    @pytest.mark.usefixtures('gl')
    def test_skin_pose_moves_the_vertices(self):
        mesh = self._skinned()
        assert mesh.is_deformable is True

        mesh.set_skin_matrices(self._shift_x(5.0))

        assert mesh.posed_positions()[0][0] == pytest.approx(5.0)
        mesh._gpu(_mode())
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_the_shader_path_leaves_the_buffers_at_rest(self):
        """Nothing is re-uploaded per frame: the pose is a palette of matrices."""
        mesh = self._skinned()

        mesh.set_skin_matrices(self._shift_x(5.0))

        assert mesh.skin_on_gpu is True
        assert mesh.deforms_vertices is False
        assert mesh.positions[0][0] == pytest.approx(0.0)
        assert set(mesh._gpu(_mode()).dyn) == set()

    @pytest.mark.usefixtures('gl')
    def test_the_cpu_path_deforms_the_arrays_and_re_uploads(self):
        mesh = self._skinned()
        mesh.skin_on_gpu = False

        mesh.set_skin_matrices(self._shift_x(5.0))

        assert mesh.deforms_vertices is True
        assert mesh.positions[0][0] == pytest.approx(5.0)
        assert set(mesh._gpu(_mode()).dyn) == {'positions', 'normals', 'tangents'}
        assert glGetError() == GL_NO_ERROR


class TestResourcesAndQueue:
    @pytest.mark.usefixtures('gl')
    def test_release_clears_vaos(self):
        gpu = _full_mesh()._gpu(_mode())
        assert gpu.vao != 0
        gpu.release()
        assert gpu.vao == 0
        gpu.release()                                # idempotent

    @pytest.mark.usefixtures('gl')
    def test_a_rebuilt_instance_vao_is_given_the_divisor_it_is_drawn_with(self):
        """The divisor is state of the VAO, so a new VAO starts from its own."""
        gpu = _full_mesh()._gpu(_mode())
        modelviews = [np.eye(4, dtype='f')] * 2

        def divisor():
            GL.glBindVertexArray(gpu._instance_vao)
            try:
                return int(np.ravel(GL.glGetVertexAttribiv(
                    instancing.INSTANCE_ATTR_LOC, GL.GL_VERTEX_ATTRIB_ARRAY_DIVISOR))[0])
            finally:
                GL.glBindVertexArray(0)

        instancing.draw_instanced_mesh(gpu, modelviews, [0, 0], copies=3)
        assert divisor() == 3
        gpu.release()
        instancing.draw_instanced_mesh(gpu, modelviews, [0, 0], copies=3)
        assert divisor() == 3
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_instance_gpu_returns_cached_gpu(self):
        mesh = _full_mesh()
        mode = _mode()
        assert mesh.instanceGPU(mode) is mesh._gpu(mode)

    @pytest.mark.usefixtures('gl')
    def test_finalizer_enqueues_then_flush_deletes(self):
        mesh = _full_mesh()
        mode = _mode()
        queue = PBRMesh._pending_delete_queue(mode)
        gpu = _MeshGPU(mesh, pending_deletes=queue)
        vao_id = gpu.vao
        del gpu
        gc.collect()                                 # finalizer hands the id to the queue
        assert vao_id in queue
        PBRMesh.flush_pending_deletes(mode)          # deletes with the context current
        assert queue == []
        assert glGetError() == GL_NO_ERROR


class TestBoundingAndMisc:
    @pytest.mark.usefixtures('gl')
    def test_bounding_volume_from_points(self):
        vol = _full_mesh().boundingVolume(None)
        assert vol is not None

    def test_bounding_volume_empty_mesh(self):
        vol = PBRMesh(positions=np.zeros((0, 3), 'f')).boundingVolume(None)
        assert vol is not None

    def test_front_face_bad_matrix_defaults_ccw(self):
        assert PBRMesh(positions=np.zeros((3, 3), 'f'))._front_face(np.eye(2)) == GL_CCW

    def test_front_face_none_matrix_defaults_ccw(self):
        assert PBRMesh(positions=np.zeros((3, 3), 'f'))._front_face(None) == GL_CCW

    def test_morph_weights_move_the_deform_version(self):
        mesh = PBRMesh(
            positions=np.zeros((3, 3), 'f'),
            morph_targets=[{'positions': np.ones((3, 3), 'f')}])
        assert mesh.deform_version == 0
        mesh.set_morph_weights([1.0])
        assert mesh.deform_version == 1

    def test_set_morph_weights_noop_without_targets(self):
        mesh = PBRMesh(positions=np.zeros((3, 3), 'f'))
        mesh.set_morph_weights([1.0])                 # no targets -> silent no-op
        assert mesh.deform_version == 0

    def test_set_skin_matrices_noop_without_joints(self):
        mesh = PBRMesh(positions=np.zeros((3, 3), 'f'))
        mesh.set_skin_matrices(np.eye(4)[None])       # no joints -> silent no-op
        assert mesh.deform_version == 0

    def test_flat_position_array_is_reshaped(self):
        mesh = PBRMesh(positions=np.array([0, 0, 0, 1, 0, 0], 'f'))   # 1-D input
        assert mesh.positions.shape == (2, 3)

    def test_sort_key_reports_material_transparency(self):
        opaque = PBRMesh(positions=np.zeros((3, 3), 'f'), material=None)
        assert opaque.sortKey(None, None)[0] is False
        clear = PBRMesh(positions=np.zeros((3, 3), 'f'),
                        material=PBRMaterial(alphaMode='BLEND'))
        assert clear.sortKey(None, None)[0] is True


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class _DepthProgram:
    """What a depth draw asks of the pass's program: whether it is skinned."""

    def __init__(self):
        self.skinning = []
        self.program = 0

    def set_skinning(self, base):
        self.skinning.append(base)


class TestDrawingIntoADepthMap:
    """``depthDraw``: a mesh draws its positions into a shadow map with the
    least the depth pass needs, and says when it needs the whole draw."""

    def _depth_mode(self):
        return _mode(shadow_pass=True, shader_program=_DepthProgram())

    @pytest.mark.usefixtures('gl')
    def test_a_plain_mesh_draws_itself(self):
        mode = self._depth_mode()
        assert _full_mesh().depthDraw(mode) is True
        assert glGetError() == GL_NO_ERROR
        # The uniform outlives the draw that set it: a plain mesh says it is
        # not skinned, whatever drew before it.
        assert mode.shader_program.skinning == [None]

    @pytest.mark.usefixtures('gl')
    def test_an_unindexed_mesh_draws_itself(self):
        assert _full_mesh(indices=None).depthDraw(self._depth_mode()) is True
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_a_morphed_mesh_is_drawn_posed(self):
        mesh = TestDynamicDeform()._morph_mesh()
        mode = self._depth_mode()
        gpu = mesh._gpu(mode)
        before = gpu._uploaded_morph_version
        mesh.set_morph_weights([1.0])
        assert mesh.depthDraw(mode) is True
        assert gpu._uploaded_morph_version != before

    @pytest.mark.usefixtures('gl')
    def test_a_skinned_mesh_asks_for_the_whole_draw(self):
        mesh = _full_mesh()
        mesh.skin_joints = np.zeros((3, 4), 'f')
        assert mesh.depthDraw(self._depth_mode()) is False

    @pytest.mark.usefixtures('gl')
    def test_an_empty_mesh_draws_nothing(self):
        empty = PBRMesh(positions=np.zeros((0, 3), 'f'))
        assert empty.depthDraw(self._depth_mode()) is True

    @pytest.mark.usefixtures('gl')
    def test_a_shape_draws_its_mesh_into_the_depth_map_that_way(self):
        mesh = _full_mesh()
        drawn = []
        mesh.depthDraw = lambda mode: drawn.append(mode) or True
        mode = self._depth_mode()
        Shape(geometry=mesh).Render(mode=mode)
        assert drawn == [mode]
