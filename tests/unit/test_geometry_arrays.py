"""What a geometry node offers, described once and bound once.

A geometry keeps its vertices in separate buffers, or interleaved in one, or in
whatever a raw-GL layer builds for itself. ``GeometryArrays`` is the one
description all of those turn into, keyed by the vertex semantics
``vertexsemantics`` declares, and ``bind_geometry`` is the one function that
turns a description into a vertex array object.
"""
import numpy as np
from OpenGL.GL import (
    GL_TRIANGLE_STRIP, GL_UNSIGNED_SHORT,
    GL_VERTEX_ATTRIB_ARRAY_ENABLED, GL_VERTEX_ATTRIB_ARRAY_SIZE,
    GL_VERTEX_ATTRIB_ARRAY_STRIDE,
    glBindVertexArray, glGetVertexAttribiv,
)
from OpenGL.arrays import vbo

from OpenGLContext.scenegraph import vertexsemantics as vs
from OpenGLContext.scenegraph.geometryarrays import GeometryArrays, bind_geometry
from OpenGLContext.scenegraph.shadergeometry import VertexFormat


def a_buffer(rows=3, columns=3):
    return vbo.VBO(np.zeros((rows, columns), dtype='f'))


class TestDescribingWhatAGeometryHas:
    def test_separate_buffers_are_keyed_by_semantic(self):
        positions, normals = a_buffer(), a_buffer()
        arrays = GeometryArrays.separate(
            count=3, positions=positions, normals=normals)
        assert set(arrays.arrays) == {'POSITION', 'NORMAL'}
        assert arrays.arrays['POSITION'].buffer is positions
        assert arrays.arrays['POSITION'].components == 3

    def test_an_array_a_geometry_does_not_have_is_simply_absent(self):
        arrays = GeometryArrays.separate(count=3, positions=a_buffer())
        assert set(arrays.arrays) == {'POSITION'}

    def test_a_texcoord_is_two_components(self):
        arrays = GeometryArrays.separate(
            count=3, positions=a_buffer(), texcoords=a_buffer(columns=2))
        assert arrays.arrays['TEXCOORD_0'].components == 2

    def test_an_interleaved_buffer_becomes_one_entry_per_semantic(self):
        buffer = a_buffer(columns=8)
        arrays = GeometryArrays.interleaved(
            buffer, VertexFormat.T2F_N3F_V3F, count=3)
        assert set(arrays.arrays) == {'TEXCOORD_0', 'NORMAL', 'POSITION'}
        position = arrays.arrays['POSITION']
        assert (position.offset, position.stride, position.components) == (20, 32, 3)
        assert arrays.arrays['TEXCOORD_0'].offset == 0
        assert all(entry.buffer is buffer for entry in arrays.arrays.values())

    def test_the_quadric_layout_puts_position_first(self):
        arrays = GeometryArrays.interleaved(
            a_buffer(columns=8), VertexFormat.V3F_T2F_N3F, count=3)
        assert arrays.arrays['POSITION'].offset == 0
        assert arrays.arrays['NORMAL'].offset == 20

    def test_the_draw_mode_and_count_travel_with_the_arrays(self):
        arrays = GeometryArrays.separate(
            count=17, positions=a_buffer(), draw_mode=GL_TRIANGLE_STRIP)
        assert (arrays.count, arrays.draw_mode) == (17, GL_TRIANGLE_STRIP)

    def test_indexed_geometry_carries_its_index_buffer(self):
        indices = vbo.VBO(np.zeros((3,), dtype='H'),
                          target='GL_ELEMENT_ARRAY_BUFFER')
        arrays = GeometryArrays.separate(
            count=3, positions=a_buffer(), indices=indices,
            index_type=GL_UNSIGNED_SHORT)
        assert arrays.indices is indices
        assert arrays.indexed


class TestBindingThem:
    def test_each_semantic_is_enabled_at_the_location_the_table_says(self, gl_context):
        arrays = GeometryArrays.separate(
            count=3, positions=a_buffer(), normals=a_buffer(),
            texcoords=a_buffer(columns=2))
        vao = bind_geometry(arrays)
        glBindVertexArray(vao)
        try:
            for semantic, components in (
                ('POSITION', 3), ('NORMAL', 3), ('TEXCOORD_0', 2),
            ):
                location = vs.location(semantic)
                assert int(glGetVertexAttribiv(
                    location, GL_VERTEX_ATTRIB_ARRAY_ENABLED)[0]), semantic
                assert int(glGetVertexAttribiv(
                    location, GL_VERTEX_ATTRIB_ARRAY_SIZE)[0]) == components
        finally:
            glBindVertexArray(0)

    def test_an_interleaved_buffer_records_its_stride(self, gl_context):
        arrays = GeometryArrays.interleaved(
            a_buffer(columns=8), VertexFormat.T2F_N3F_V3F, count=3)
        vao = bind_geometry(arrays)
        glBindVertexArray(vao)
        try:
            assert int(glGetVertexAttribiv(
                vs.LOC_POSITION, GL_VERTEX_ATTRIB_ARRAY_STRIDE)[0]) == 32
        finally:
            glBindVertexArray(0)

    def test_a_second_bind_of_the_same_arrays_reuses_the_object(self, gl_context):
        class Owner:
            pass
        owner, arrays = Owner(), GeometryArrays.separate(
            count=3, positions=a_buffer())
        assert bind_geometry(arrays, owner=owner) == bind_geometry(
            arrays, owner=owner)

    def test_new_buffers_rebuild_it_rather_than_binding_stale_pointers(self, gl_context):
        """A data change makes new VBOs; the recorded pointers must follow."""
        class Owner:
            pass
        owner = Owner()
        bind_geometry(GeometryArrays.separate(count=3, positions=a_buffer()),
                      owner=owner)
        replacement = a_buffer()
        bind_geometry(
            GeometryArrays.separate(count=3, positions=replacement), owner=owner)
        cached_refs, _vao = owner._shader_vao_cache[0]
        assert replacement in cached_refs
