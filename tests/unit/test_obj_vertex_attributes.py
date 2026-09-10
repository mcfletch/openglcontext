"""The OBJ loader's ``vn``/``vt`` records reach the scenegraph nodes.

``Normal`` carries its directions in ``vector`` and ``TextureCoordinate`` its
pairs in ``point``, which is what the geometry's ``normalIndex`` and
``texCoordIndex`` are indices into.
"""
from typing import Any, List, Tuple

from OpenGLContext.loaders.obj import OBJHandler
from OpenGLContext.scenegraph import basenodes

CUBE_FACE_OBJ = """\
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 1
f 1/1/1 2/2/1 3/3/1 4/4/1
"""


def _shapes(sg: Any) -> List[Any]:
    return [child
            for transform in sg.children
            for child in getattr(transform, 'children', [])
            if isinstance(child, basenodes.Shape)]


def _parse(tmp_path: Any) -> Tuple[Any, Any]:
    ok, sg = OBJHandler().parse(CUBE_FACE_OBJ, str(tmp_path / 'quad.obj'))
    assert ok is True
    shapes = _shapes(sg)
    assert shapes, "expected a Shape from the OBJ face"
    return sg, shapes[0].geometry


class TestVertexAttributes:
    def test_normals_reach_the_normal_node(self, tmp_path: Any) -> None:
        """``vn`` lines populate ``Normal.vector``, which normalIndex indexes."""
        _sg, geometry = _parse(tmp_path)
        vectors = [list(v) for v in geometry.normal.vector]
        assert [0.0, 0.0, 0.0] in vectors, vectors
        assert [0.0, 0.0, 1.0] in vectors, vectors
        assert max(geometry.normalIndex) < len(vectors)

    def test_texture_coordinates_reach_the_texcoord_node(self, tmp_path: Any) -> None:
        """``vt`` lines populate ``TextureCoordinate.point``."""
        _sg, geometry = _parse(tmp_path)
        points = [list(p) for p in geometry.texCoord.point]
        assert [1.0, 1.0] in points, points
        assert max(geometry.texCoordIndex) < len(points)

    def test_coordinates_reach_the_coordinate_node(self, tmp_path: Any) -> None:
        """``v`` lines populate ``Coordinate.point``, as the indices assume."""
        _sg, geometry = _parse(tmp_path)
        points = [list(p) for p in geometry.coord.point]
        assert [1.0, 1.0, 0.0] in points, points
        assert max(geometry.coordIndex) < len(points)
