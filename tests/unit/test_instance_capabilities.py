"""Headless tests for instancing capability math and per-instance packing."""
import numpy as np

from OpenGLContext.passes.instancing import (
    max_materials_per_ubo, GLCapabilities, pack_instance_buffer,
    MATERIAL_STRIDE_BYTES,
)


class TestUBOCapacity:
    def test_guaranteed_minimum_block(self):
        # 16 KB guaranteed / 176 B per material.
        assert max_materials_per_ubo(16384) == 16384 // MATERIAL_STRIDE_BYTES

    def test_desktop_64k_block(self):
        assert max_materials_per_ubo(65536) == 65536 // MATERIAL_STRIDE_BYTES

    def test_never_below_one(self):
        # A pathologically small block still lets the caller make progress.
        assert max_materials_per_ubo(8) == 1

    def test_caps_object_reports_capacity(self):
        caps = GLCapabilities(max_uniform_block_size=65536)
        assert caps.max_materials() == max_materials_per_ubo(65536)


class TestInstancePacking:
    def test_stride_is_76_bytes(self):
        # mat4 (64) + uint32 object id (4) + uint32 material index (4) + uint32
        # joint base (4). Locked because the vertex shader's attribute offsets
        # assume it.
        arr = pack_instance_buffer([np.eye(4)], [1])
        assert arr.dtype.itemsize == 76

    def test_an_unskinned_instance_names_the_start_of_the_palette(self):
        """Every instance carries a joint base; an unskinned one reads none."""
        arr = pack_instance_buffer([np.eye(4)], [1])
        assert arr['joint'][0] == 0

    def test_a_skinned_instance_carries_where_its_joints_start(self):
        arr = pack_instance_buffer([np.eye(4)] * 3, [1, 2, 3],
                                   joint_bases=[0, 57, 114])
        assert list(arr['joint']) == [0, 57, 114]

    def test_matrix_stored_row_major_contiguous(self):
        mv = np.arange(16, dtype='f').reshape(4, 4)
        arr = pack_instance_buffer([mv], [7])
        np.testing.assert_array_equal(arr['mv'][0], mv.ravel(order='C'))

    def test_object_ids_packed_per_instance(self):
        arr = pack_instance_buffer([np.eye(4), np.eye(4), np.eye(4)],
                                   [10, 20, 30])
        assert list(arr['oid']) == [10, 20, 30]

    def test_material_index_defaults_zero(self):
        arr = pack_instance_buffer([np.eye(4), np.eye(4)], [1, 2])
        assert list(arr['mat']) == [0, 0]

    def test_material_index_packed_per_instance(self):
        arr = pack_instance_buffer([np.eye(4)] * 3, [1, 2, 3],
                                   material_indices=[0, 1, 0])
        assert list(arr['mat']) == [0, 1, 0]

    def test_count_matches_instances(self):
        mvs = [np.eye(4) for _ in range(5)]
        arr = pack_instance_buffer(mvs, list(range(5)))
        assert len(arr) == 5

    def test_stacked_ndarray_matches_list_of_matrices(self):
        # R4: callers may hand a single (N,4,4) array (a batched matmul result)
        # instead of a Python list of (4,4) matrices; both must pack identically.
        mats = [np.arange(16, dtype='f').reshape(4, 4) + k for k in range(4)]
        from_list = pack_instance_buffer(mats, [1, 2, 3, 4])
        from_stack = pack_instance_buffer(np.asarray(mats, dtype='f'), [1, 2, 3, 4])
        np.testing.assert_array_equal(from_stack['mv'], from_list['mv'])
        assert list(from_stack['oid']) == [1, 2, 3, 4]
