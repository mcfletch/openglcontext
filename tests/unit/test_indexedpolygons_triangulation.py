"""Quads and quad strips become triangles, which is all a core profile draws.

``GL_QUADS`` and ``GL_QUAD_STRIP`` are fixed-function primitives; core GL has
neither.  An ``IndexedPolygons`` node that names one still describes perfectly
ordinary geometry, so the indices are rewritten into triangles rather than the
node refusing to draw.

The rewriting is plain index arithmetic, so it is tested here without GL.  The
winding of each triangle matters as much as its vertices: a face wound the wrong
way is culled, which looks exactly like not drawing it at all.
"""

import numpy as np
import pytest

from OpenGL.GL import GL_QUAD_STRIP

from OpenGLContext.scenegraph.indexedpolygons import triangulate_index


class TestTrianglesAreLeftAlone:
    def test_a_triangle_index_is_returned_unchanged(self):
        index = np.array([0, 1, 2, 3, 4, 5], 'I')
        assert triangulate_index(index, 3) is index

    def test_a_two_dimensional_triangle_index_is_returned_unchanged(self):
        index = np.array([[0, 1, 2], [3, 4, 5]], 'I')
        assert triangulate_index(index, 3) is index


class TestQuadsBecomeTwoTrianglesEach:
    def test_one_quad_becomes_two_triangles(self):
        assert triangulate_index(np.array([0, 1, 2, 3], 'I'), 4).tolist() == [
            0, 1, 2, 0, 2, 3]

    def test_two_quads_become_four_triangles(self):
        assert triangulate_index(np.array([0, 1, 2, 3, 4, 5, 6, 7], 'I'),
                                 4).tolist() == [0, 1, 2, 0, 2, 3,
                                                 4, 5, 6, 4, 6, 7]

    def test_a_trailing_partial_quad_is_dropped(self):
        """GL ignores vertices that do not complete a primitive; so does this."""
        assert triangulate_index(np.array([0, 1, 2, 3, 4, 5], 'I'),
                                 4).tolist() == [0, 1, 2, 0, 2, 3]


class TestAQuadStripBecomesATriangleStrip:
    def test_one_quad_of_strip(self):
        """``GL_QUAD_STRIP`` makes the quad (v0, v1, v3, v2), in that order."""
        assert triangulate_index(np.array([0, 1, 2, 3], 'I'),
                                 GL_QUAD_STRIP).tolist() == [0, 1, 3, 0, 3, 2]

    def test_two_quads_of_strip_share_their_edge(self):
        assert triangulate_index(np.array([0, 1, 2, 3, 4, 5], 'I'),
                                 GL_QUAD_STRIP).tolist() == [
            0, 1, 3, 0, 3, 2, 2, 3, 5, 2, 5, 4]

    def test_a_strip_too_short_for_a_quad_draws_nothing(self):
        assert triangulate_index(np.array([0, 1], 'I'),
                                 GL_QUAD_STRIP).tolist() == []

    def test_a_trailing_odd_vertex_is_dropped(self):
        assert triangulate_index(np.array([0, 1, 2, 3, 4], 'I'),
                                 GL_QUAD_STRIP).tolist() == [0, 1, 3, 0, 3, 2]


class TestEachRowOfATwoDimensionalIndexIsItsOwnPrimitive:
    """A row per strip is what the shape of such an array says, and it is what
    keeps two strips from being bridged by a sliver quad joining them."""

    def test_two_rows_of_quad_strip_do_not_join(self):
        index = np.array([[0, 1, 2, 3], [4, 5, 6, 7]], 'I')
        assert triangulate_index(index, GL_QUAD_STRIP).tolist() == [
            0, 1, 3, 0, 3, 2, 4, 5, 7, 4, 7, 6]

    def test_rows_of_quads(self):
        index = np.array([[0, 1, 2, 3], [4, 5, 6, 7]], 'I')
        assert triangulate_index(index, 4).tolist() == [
            0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]


class TestWhatItRefuses:
    def test_an_unsupported_primitive_is_reported(self):
        with pytest.raises(ValueError) as raised:
            triangulate_index(np.array([0, 1, 2, 3, 4], 'I'), 5)
        assert '5' in str(raised.value)

    def test_an_empty_index_gives_an_empty_result(self):
        assert triangulate_index(np.array([], 'I'), 4).tolist() == []
