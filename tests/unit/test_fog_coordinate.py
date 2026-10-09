"""X3D's FogCoordinate: a fog depth given per vertex in place of the distance.

Each vertex's depth, 0 to 1, is the share of the fog colour it takes: X_ITE's
reading of the depth replacing the depth worked out from the visibility
range. A geometry with fewer depths than vertices gives the last to the rest.
The depths reach the vertex shader in a buffer texture read by gl_VertexID,
so they take no attribute location.
"""
import numpy as np
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import meshgeometry


def test_the_mesh_carries_a_depth_per_vertex():
    quad = meshgeometry.IndexedTriangleSet(
        index=[0, 1, 2, 0, 2, 3],
        coord=x3d.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]),
        fogCoord=x3d.FogCoordinate(depth=[0.0, 1.0, 1.0, 0.0]))
    mesh = quad.mesh()
    assert np.allclose(mesh.fog_depths, (0.0, 1.0, 1.0, 0.0))


def test_a_short_list_gives_its_last_depth_to_the_rest():
    quad = meshgeometry.IndexedTriangleSet(
        index=[0, 1, 2, 0, 2, 3],
        coord=x3d.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]),
        fogCoord=x3d.FogCoordinate(depth=[0.25, 0.5]))
    assert np.allclose(quad.mesh().fog_depths, (0.25, 0.5, 0.5, 0.5))


def test_corners_with_their_own_vertices_read_their_coordinates_depth():
    quad = meshgeometry.IndexedTriangleSet(
        index=[0, 1, 2, 0, 2, 3], normalPerVertex=False,
        normal=x3d.Normal(vector=[(0, 0, 1), (0, 0, 1)]),
        coord=x3d.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]),
        fogCoord=x3d.FogCoordinate(depth=[0.0, 0.1, 0.2, 0.3]))
    assert np.allclose(quad.mesh().fog_depths, (0.0, 0.1, 0.2, 0.0, 0.2, 0.3))


def test_without_one_the_mesh_has_none():
    quad = meshgeometry.IndexedTriangleSet(
        index=[0, 1, 2], coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]))
    assert quad.mesh().fog_depths is None


WALL = b'''<X3D version="4.0"><Scene>
  <Background skyColor="0 0 0"/><Viewpoint position="0 0 3"/>
  <Fog color="0 0 1" visibilityRange="1000"/>
  <Shape><Appearance><Material diffuseColor="0 0 0" emissiveColor="1 0 0"/></Appearance>
    <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
      <Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>
      <FogCoordinate depth="0 1 1 0"/></IndexedTriangleSet></Shape>
</Scene></X3D>'''


def test_the_depths_fog_the_surface(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(WALL, 'fogged.x3d')
    with scene_context(scene, size=(64, 64)) as context:
        image = drawn_image(context).astype(int)
    left, right = image[32, 14], image[32, 50]
    assert left[0] > 150 and left[2] < 100, left
    assert right[2] > 150 and right[0] < 100, right
