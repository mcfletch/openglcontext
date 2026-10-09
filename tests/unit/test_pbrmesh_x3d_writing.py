"""A PBRMesh written to X3D as standard geometry, and read back the same.

The mesh's triangles are an `IndexedTriangleSet` with `Coordinate`, `Normal`,
`TextureCoordinate` (a `MultiTextureCoordinate` of two where it has a second
set), `Tangent` and `Color` or `ColorRGBA` as it has them; its points a
`PointSet` and its lines an `IndexedLineSet`. Read with the engine's
prototypes, every triangle corner has the values it was written with.
"""
import numpy as np
import pytest
from OpenGL.GL import GL_LINE_STRIP, GL_LINES, GL_POINTS, GL_TRIANGLE_FAN, GL_TRIANGLE_STRIP
from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d
from vrml.x3d.scene import X3DScene

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

ENCODINGS = ('xml', 'classic', 'json')

QUAD = dict(
    positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
    normals=np.array([(0, 0, 1)] * 4, 'f'),
    texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
    indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
)


def read_back(mesh, encoding='xml'):
    """`mesh`, in a Shape, written in `encoding` and read with the engine's nodes"""
    scene = X3DScene(children=[x3d.Shape(geometry=mesh)])
    text = vrml_x3d.dumps(scene, encoding=encoding)
    read = vrml_x3d.loads(text, prototypes=prototypes())
    assert not [problem for problem in read.problems if problem.severity == 'error']
    return read.children[0].geometry


def corners(mesh, name):
    """`mesh`'s array `name`, one row per triangle corner"""
    values = getattr(mesh, name)
    return values if mesh.indices is None else values[mesh.indices]


@pytest.mark.parametrize('encoding', ENCODINGS)
def test_the_arrays_are_written_as_an_indexed_triangle_set(encoding):
    mesh = PBRMesh(solid=False, **QUAD)
    found = read_back(mesh, encoding)
    assert isinstance(found, x3d.IndexedTriangleSet)
    assert not found.solid
    drawn = found.mesh()
    for name in ('positions', 'normals', 'texcoords'):
        assert np.allclose(corners(drawn, name), corners(mesh, name)), name


def test_tangents_colours_and_a_second_set_are_written():
    rng = np.random.default_rng(3)
    mesh = PBRMesh(
        tangents=np.array([(1, 0, 0, -1)] * 4, 'f'),
        colors=rng.random((4, 4)).astype('f'),
        texcoords1=rng.random((4, 2)).astype('f'),
        **QUAD)
    found = read_back(mesh)
    assert isinstance(found.color, x3d.ColorRGBA)
    assert isinstance(found.texCoord, x3d.MultiTextureCoordinate)
    assert [entry.mapping for entry in found.texCoord.texCoord] == ['TEXCOORD_0', 'TEXCOORD_1']
    drawn = found.mesh()
    for name in ('tangents', 'colors', 'texcoords', 'texcoords1'):
        assert np.allclose(corners(drawn, name), corners(mesh, name), atol=1e-6), name


def test_opaque_colours_are_a_color_node():
    mesh = PBRMesh(colors=np.array([(1, 0, 0)] * 4, 'f'), **QUAD)
    found = read_back(mesh)
    assert isinstance(found.color, x3d.Color)
    assert np.allclose(corners(found.mesh(), 'colors'), corners(mesh, 'colors'))


def test_an_unindexed_mesh_takes_its_vertices_three_at_a_time():
    soup = QUAD['positions'][QUAD['indices']]
    found = read_back(PBRMesh(positions=soup))
    assert np.allclose(corners(found.mesh(), 'positions'), soup)


@pytest.mark.parametrize('mode, triangles', [
    (GL_TRIANGLE_STRIP, [(0, 1, 2), (2, 1, 3)]),
    (GL_TRIANGLE_FAN, [(0, 1, 2), (0, 2, 3)]),
])
def test_strips_and_fans_are_written_as_their_triangles(mode, triangles):
    points = QUAD['positions']
    found = read_back(PBRMesh(positions=points, draw_mode=mode))
    expected = points[np.array(triangles).ravel()]
    assert np.allclose(corners(found.mesh(), 'positions'), expected)


def test_a_vertex_attribute_is_written_by_name():
    weights = np.arange(8, dtype='f').reshape(4, 2)
    found = read_back(PBRMesh(vertex_attributes=[('weight', weights, 1)], **QUAD))
    attribute, = found.attrib
    assert (attribute.name, int(attribute.numComponents)) == ('weight', 2)
    assert np.allclose(np.asarray(attribute.value).reshape(-1, 2), weights)


def test_points_are_a_point_set():
    points = QUAD['positions']
    found = read_back(PBRMesh(positions=points, colors=np.ones((4, 3), 'f'),
                              draw_mode=GL_POINTS))
    assert isinstance(found, x3d.PointSet)
    assert np.allclose(np.asarray(found.coord.point), points)
    assert len(found.color.color) == 4


@pytest.mark.parametrize('mode, index', [
    (GL_LINES, [0, 1, -1, 2, 3, -1]),
    (GL_LINE_STRIP, [0, 1, 2, 3, -1]),
])
def test_lines_are_an_indexed_line_set(mode, index):
    found = read_back(PBRMesh(positions=QUAD['positions'], draw_mode=mode))
    assert isinstance(found, x3d.IndexedLineSet)
    assert list(found.coordIndex) == index


def test_an_empty_mesh_is_an_empty_set():
    found = read_back(PBRMesh())
    assert isinstance(found, x3d.IndexedTriangleSet)
    assert not len(found.index)
