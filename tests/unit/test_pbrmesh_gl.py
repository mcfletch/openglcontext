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

glfw = pytest.importorskip("glfw")
from vrml.cache import Cache  # noqa: E402
from OpenGL.GL import (  # noqa: E402
    GL_POINTS, GL_TRIANGLES, glGetError, GL_NO_ERROR,
)

from OpenGLContext.scenegraph.pbrmesh import PBRMesh, _MeshGPU  # noqa: E402


@pytest.fixture
def gl():
    if not glfw.init():
        pytest.skip("glfw init failed (no GL)")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    win = glfw.create_window(64, 64, "pbrmesh", None, None)
    if not win:
        glfw.terminate()
        pytest.skip("no core-profile GL context available")
    glfw.make_context_current(win)
    try:
        yield win
    finally:
        glfw.destroy_window(win)
        glfw.terminate()


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
    def test_indexed_mesh_builds_all_attribute_buffers(self, gl):
        mesh = _full_mesh()
        gpu = mesh._gpu(_mode())
        assert gpu.vao is not None
        assert gpu.indexed is True
        assert gpu.count == 3
        assert len(gpu.attr_layout) == 6          # all six optional attrs present
        assert set(gpu.dyn) == {'positions', 'normals', 'tangents'}
        assert glGetError() == GL_NO_ERROR

    def test_non_indexed_mesh_counts_vertices(self, gl):
        gpu = _full_mesh(indices=None)._gpu(_mode())
        assert gpu.indexed is False
        assert gpu.count == 3                       # vertex count, not index count
        assert gpu.idx_vbo is None

    def test_gpu_is_cached_per_context(self, gl):
        mesh = _full_mesh()
        mode = _mode()
        assert mesh._gpu(mode) is mesh._gpu(mode)   # second call reuses the VAO


class TestRenderDraw:
    def test_render_indexed_triangles(self, gl):
        assert _full_mesh().render(mode=_mode()) == 1

    def test_render_non_indexed_array(self, gl):
        assert _full_mesh(indices=None).render(mode=_mode()) == 1

    def test_render_points_mode(self, gl):
        # GL_POINTS enables GL_PROGRAM_POINT_SIZE around the draw.
        assert _full_mesh(draw_mode=GL_POINTS).render(mode=_mode()) == 1

    def test_render_skips_without_shader_mode(self, gl):
        assert _full_mesh().render(mode=_mode(shader_mode=False)) == 1

    def test_render_skips_empty_mesh(self, gl):
        empty = PBRMesh(positions=np.zeros((0, 3), 'f'))
        assert empty.render(mode=_mode()) == 1

    def test_render_sets_vertex_color_uniform(self, gl):
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

    def test_morph_reupload_on_weight_change(self, gl):
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

    def test_zero_weight_morph_target_is_skipped(self, gl):
        # Two targets, only the first active: the zero-weight target is skipped in
        # the deform accumulation but the active one still applies.
        p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
        mesh = PBRMesh(
            positions=p,
            morph_targets=[{'positions': np.tile([0, 0, 2], (3, 1)).astype('f')},
                           {'positions': np.tile([0, 0, 9], (3, 1)).astype('f')}])
        mesh.set_morph_weights([1.0, 0.0])           # second weight 0 -> skipped
        assert mesh.positions[0][2] == pytest.approx(2.0)   # only target 0 applied

    def test_skin_deform_transforms_positions(self, gl):
        p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
        mesh = PBRMesh(
            positions=p,
            normals=np.tile([0, 0, 1], (3, 1)).astype('f'),
            tangents=np.tile([1, 0, 0, 1], (3, 1)).astype('f'),
            skin_joints=np.zeros((3, 4), np.uint32),
            skin_weights=np.tile([1, 0, 0, 0], (3, 1)).astype('f'))
        assert mesh.is_deformable is True
        translate = np.eye(4)
        translate[3, 0] = 5.0                        # row-vector translation +x
        mesh.set_skin_matrices(np.stack([translate]))
        assert mesh.positions[0][0] == pytest.approx(5.0)
        mesh._gpu(_mode())                           # uploads deformed arrays
        assert glGetError() == GL_NO_ERROR


class TestResourcesAndQueue:
    def test_release_clears_vaos(self, gl):
        gpu = _full_mesh()._gpu(_mode())
        assert gpu.vao is not None
        gpu.release()
        assert gpu.vao is None
        gpu.release()                                # idempotent

    def test_instance_gpu_returns_cached_gpu(self, gl):
        mesh = _full_mesh()
        mode = _mode()
        assert mesh.instanceGPU(mode) is mesh._gpu(mode)

    def test_finalizer_enqueues_then_flush_deletes(self, gl):
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
    def test_bounding_volume_from_points(self, gl):
        vol = _full_mesh().boundingVolume(None)
        assert vol is not None

    def test_bounding_volume_empty_mesh(self):
        vol = PBRMesh(positions=np.zeros((0, 3), 'f')).boundingVolume(None)
        assert vol is not None

    def test_front_face_bad_matrix_defaults_ccw(self):
        from OpenGL.GL import GL_CCW
        assert PBRMesh(positions=np.zeros((3, 3), 'f'))._front_face(np.eye(2)) == GL_CCW

    def test_front_face_none_matrix_defaults_ccw(self):
        from OpenGL.GL import GL_CCW
        assert PBRMesh(positions=np.zeros((3, 3), 'f'))._front_face(None) == GL_CCW

    def test_morph_version_alias_tracks_deform_version(self):
        mesh = PBRMesh(
            positions=np.zeros((3, 3), 'f'),
            morph_targets=[{'positions': np.ones((3, 3), 'f')}])
        assert mesh._morph_version == mesh._deform_version
        mesh.set_morph_weights([1.0])
        assert mesh._morph_version == mesh._deform_version == 1

    def test_set_morph_weights_noop_without_targets(self):
        mesh = PBRMesh(positions=np.zeros((3, 3), 'f'))
        mesh.set_morph_weights([1.0])                 # no targets -> silent no-op
        assert mesh._deform_version == 0

    def test_set_skin_matrices_noop_without_joints(self):
        mesh = PBRMesh(positions=np.zeros((3, 3), 'f'))
        mesh.set_skin_matrices(np.eye(4)[None])       # no joints -> silent no-op
        assert mesh._deform_version == 0

    def test_flat_position_array_is_reshaped(self):
        mesh = PBRMesh(positions=np.array([0, 0, 0, 1, 0, 0], 'f'))   # 1-D input
        assert mesh.positions.shape == (2, 3)

    def test_sort_key_reports_material_transparency(self):
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        opaque = PBRMesh(positions=np.zeros((3, 3), 'f'), material=None)
        assert opaque.sortKey(None, None)[0] is False
        clear = PBRMesh(positions=np.zeros((3, 3), 'f'),
                        material=PBRMaterial(alphaMode='BLEND'))
        assert clear.sortKey(None, None)[0] is True


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
