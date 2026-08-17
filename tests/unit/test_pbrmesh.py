

class TestVertexColoursOfEitherWidth:
    """glTF's COLOR_0 is VEC3 or VEC4, and a mesher that has no transparency to
    express writes RGB. The attribute the shader reads is four wide either way,
    so a three-wide array has to be widened rather than handed over to be read
    past the end of."""

    def _mesh(self, colors):
        import numpy as np
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        return PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f'),
            colors=colors)

    def test_rgb_arrives_as_rgba(self) -> None:
        import numpy as np
        mesh = self._mesh(np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1)], 'f'))
        assert mesh.colors.shape == (3, 4)
        assert np.allclose(mesh.colors[:, :3],
                           [(1, 0, 0), (0, 1, 0), (0, 0, 1)])

    def test_what_it_gains_is_opaque(self) -> None:
        import numpy as np
        mesh = self._mesh(np.array([(1, 0, 0)] * 3, 'f'))
        assert np.allclose(mesh.colors[:, 3], 1.0)

    def test_rgba_is_left_as_it_is(self) -> None:
        import numpy as np
        given = np.array([(1, 0, 0, 0.5)] * 3, 'f')
        assert np.allclose(self._mesh(given).colors, given)

    def test_a_flat_list_is_still_read_four_at_a_time(self) -> None:
        import numpy as np
        mesh = self._mesh(np.arange(12, dtype='f'))
        assert mesh.colors.shape == (3, 4)

    def test_no_colours_is_no_colours(self) -> None:
        assert self._mesh(None).colors is None
