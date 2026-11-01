import numpy as np
from OpenGL.GL import GL_LINES, GL_POINTS

from OpenGLContext.scenegraph.pbrmesh import PBRMesh


class TestVertexColoursOfEitherWidth:
    """glTF's COLOR_0 is VEC3 or VEC4, and a mesher that has no transparency to
    express writes RGB. The attribute the shader reads is four wide either way,
    so a three-wide array has to be widened rather than handed over to be read
    past the end of."""

    def _mesh(self, colors):
        return PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f'),
            colors=colors)

    def test_rgb_arrives_as_rgba(self) -> None:
        mesh = self._mesh(np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1)], 'f'))
        assert mesh.colors.shape == (3, 4)
        assert np.allclose(mesh.colors[:, :3],
                           [(1, 0, 0), (0, 1, 0), (0, 0, 1)])

    def test_what_it_gains_is_opaque(self) -> None:
        mesh = self._mesh(np.array([(1, 0, 0)] * 3, 'f'))
        assert np.allclose(mesh.colors[:, 3], 1.0)

    def test_rgba_is_left_as_it_is(self) -> None:
        given = np.array([(1, 0, 0, 0.5)] * 3, 'f')
        assert np.allclose(self._mesh(given).colors, given)

    def test_a_flat_list_is_still_read_four_at_a_time(self) -> None:
        mesh = self._mesh(np.arange(12, dtype='f'))
        assert mesh.colors.shape == (3, 4)

    def test_no_colours_is_no_colours(self) -> None:
        assert self._mesh(None).colors is None


class TestNormalsOfLinesAndPoints:
    """A line or a point has no surface to have a normal of, and the shader
    cannot draw without one, so a mesh of either is given one facing +Z."""

    POSITIONS = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f')

    def test_lines_are_given_a_constant_normal(self) -> None:
        mesh = PBRMesh(positions=self.POSITIONS, draw_mode=GL_LINES)
        assert np.array_equal(mesh.normals, [(0, 0, 1)] * 3)

    def test_points_are_given_a_constant_normal(self) -> None:
        mesh = PBRMesh(positions=self.POSITIONS, draw_mode=GL_POINTS)
        assert mesh.normals.shape == (3, 3)

    def test_normals_the_mesh_was_given_are_kept(self) -> None:
        given = np.array([(1, 0, 0)] * 3, 'f')
        mesh = PBRMesh(positions=self.POSITIONS, normals=given, draw_mode=GL_LINES)
        assert np.array_equal(mesh.normals, given)

    def test_a_mesh_of_no_positions_has_no_normals(self) -> None:
        assert PBRMesh(draw_mode=GL_LINES).normals is None

    def test_triangles_are_left_to_the_caller(self) -> None:
        assert PBRMesh(positions=self.POSITIONS).normals is None
