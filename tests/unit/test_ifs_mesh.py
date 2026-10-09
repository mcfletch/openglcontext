"""IndexedFaceSet drawn as the mesh its fields build, as the triangle sets are.

The tessellated faces are a `PBRMesh` (`mesh()`), with every texture
coordinate set of a `MultiTextureCoordinate`, a `Tangent` indexed as the
normals are, and the `attrib` values; the mesh is kept until a field it is
built from is set.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes, meshgeometry
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.testing.scenes import drawn_image, scene_context

POINTS = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]


def quad(**named):
    named.setdefault('coord', basenodes.Coordinate(point=POINTS))
    return basenodes.IndexedFaceSet(coordIndex=[0, 1, 2, 3, -1], **named)


def by_point(mesh, values):
    """`values` keyed by the position each row is drawn at"""
    return {tuple(np.round(point, 4)): tuple(np.round(value, 4))
            for point, value in zip(mesh.positions, values)}


def test_a_face_set_is_drawn_as_a_mesh():
    found = quad()
    assert isinstance(found, meshgeometry.MeshDrawn)
    mesh = found.mesh()
    assert len(mesh.positions) == 6
    assert np.allclose(mesh.normals, (0, 0, 1))


def test_every_set_of_a_multi_texture_coordinate_is_drawn():
    first = x3d.TextureCoordinate(point=[(0, 0), (1, 0), (1, 1), (0, 1)], mapping='base')
    second = x3d.TextureCoordinate(point=[(0, 0), (2, 0), (2, 2)], mapping='detail')
    found = quad(texCoord=x3d.MultiTextureCoordinate(texCoord=[first, second]),
                 texCoordIndex=[0, 1, 2, 2, -1])
    mesh = found.mesh()
    assert by_point(mesh, mesh.texcoords)[(1, 1, 0)] == (1, 1)
    assert by_point(mesh, mesh.texcoords1) == {
        (-1, -1, 0): (0, 0), (1, -1, 0): (2, 0), (1, 1, 0): (2, 2), (-1, 1, 0): (2, 2)}
    assert found.textureCoordinateSet('detail') == 1


def test_a_tangent_is_indexed_as_the_normals_are():
    tangent = x3d.Tangent(vector=[(1, 0, 0, 1), (0, 1, 0, -1)])
    mesh = quad(tangent=tangent, normalIndex=[0, 0, 1, 1, -1]).mesh()
    assert by_point(mesh, mesh.tangents)[(-1, -1, 0)] == (1, 0, 0, 1)
    assert by_point(mesh, mesh.tangents)[(1, 1, 0)] == (0, 1, 0, -1)


def test_rgba_colours_reach_the_mesh():
    mesh = quad(color=x3d.ColorRGBA(color=[(1, 0, 0, 0.5)] * 4)).mesh()
    assert np.allclose(mesh.colors, (1, 0, 0, 0.5))


def test_attributes_are_one_per_coordinate():
    heat = x3d.FloatVertexAttribute(name='heat', numComponents=1, value=[0, 1, 2, 3])
    mesh = quad(attrib=[heat]).mesh()
    (name, values, _locations), = mesh.vertex_attributes
    assert name == 'heat'
    assert by_point(mesh, values)[(1, 1, 0)] == (2,)


def test_clockwise_faces_are_turned_round():
    """Clockwise seen from +Z with ccw false: the faces' front is -Z"""
    mesh = quad(ccw=False, solid=False).mesh()
    first = np.asarray(mesh.positions[:3], np.float64)
    assert np.cross(first[1] - first[0], first[2] - first[0])[2] < 0
    assert np.allclose(mesh.normals, (0, 0, -1))


def test_the_mesh_follows_its_fields():
    coord = basenodes.Coordinate(point=POINTS)
    colour = basenodes.Color(color=[(1, 0, 0)] * 4)
    found = quad(coord=coord, color=colour)
    check_memo_inputs(lambda: (found.mesh().positions.tolist(),
                               found.mesh().colors.tolist()), [
        ('coord.point', lambda: setattr(coord, 'point', [(0, 0, 0), (2, 0, 0), (2, 2, 0),
                                                         (0, 2, 0)])),
        ('color.color', lambda: setattr(colour, 'color', [(0, 1, 0)] * 4)),
        ('coordIndex', lambda: setattr(found, 'coordIndex', [0, 1, 2, -1])),
    ], fresh=lambda: (found.buildMesh().positions.tolist(),
                      found.buildMesh().colors.tolist()))


def test_its_triangles_are_its_meshs():
    found = quad()
    arrays = found.meshArrays()
    assert len(arrays.attributes['POSITION']) == 6


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_face_set_draws_as_the_triangle_set_of_its_faces(gl_context, renderer):
    """The same quad, as an IndexedFaceSet and as an IndexedTriangleSet, draws the same"""
    colours = '<Color color="1 0 0 0 1 0 0 0 1 1 1 0"/>'
    face = ('<IndexedFaceSet coordIndex="0 1 2 3 -1"><Coordinate point="-1 -1 0 1 -1 0 '
            '1 1 0 -1 1 0"/>%s</IndexedFaceSet>' % colours)
    triangles = ('<IndexedTriangleSet index="0 1 2 0 2 3"><Coordinate point="-1 -1 0 1 -1 0 '
                 '1 1 0 -1 1 0"/>%s</IndexedTriangleSet>' % colours)

    def draw(geometry):
        scene = Loader.loads((
            '<X3D version="4.0"><Scene><Viewpoint position="0 0 3"/><NavigationInfo '
            'headlight="false"/><Shape><Appearance><UnlitMaterial/></Appearance>%s</Shape>'
            '</Scene></X3D>' % geometry).encode(), 'scene.x3d')
        with scene_context(scene, size=(48, 48), renderer=renderer) as context:
            drawn_image(context)
            return drawn_image(context).astype(int)

    assert np.abs(draw(face) - draw(triangles)).max() <= 2
