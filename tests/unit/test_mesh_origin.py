"""Double-precision coordinates drawn exactly: a mesh's own origin.

Geometry whose points are double precision (`CoordinateDouble`,
`GeoCoordinate`, `GeoElevationGrid`) is built relative to the centre of its
points' bounds, its `meshOrigin()`, and the render pass places it by that
origin in double precision. Single-precision content has no origin. The
geometry's bounds and its `meshArrays()` stay in its own coordinates.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes, meshdata

FAR = 6378137.123


def read(body):
    document = ('<X3D version="4.0"><Scene>%s</Scene></X3D>' % body).encode()
    return Loader.loads(document, 'scene.x3d')


def far_quad(node='CoordinateDouble', geometry='IndexedTriangleSet index="0 1 2 0 2 3"'):
    """A 2 cm square at x = FAR"""
    tag = geometry.split()[0]
    points = ' '.join('%r %r %r' % (FAR, y, z) for y, z in
                      ((-0.01, -0.01), (0.01, -0.01), (0.01, 0.01), (-0.01, 0.01)))
    return read('<Shape><%s><%s point="%s"/></%s></Shape>' % (geometry, node, points, tag)
                ).children[0].geometry


@pytest.mark.parametrize('geometry', [
    'IndexedTriangleSet index="0 1 2 0 2 3"',
    'IndexedFaceSet coordIndex="0 1 2 3"',
    'QuadSet',
])
def test_double_precision_points_are_drawn_from_their_centre(geometry):
    found = far_quad(geometry=geometry)
    origin = found.meshOrigin()
    assert origin == pytest.approx((FAR, 0, 0), abs=1e-9)
    mesh = found.mesh()
    assert np.abs(mesh.positions).max() == pytest.approx(0.01, abs=1e-7)
    corner = np.asarray(mesh.positions, np.float64).min(axis=0) + origin
    assert corner == pytest.approx((FAR, -0.01, -0.01), abs=1e-7)


def test_single_precision_points_have_no_origin():
    found = far_quad(node='Coordinate')
    assert found.meshOrigin() is None


def test_the_bounds_are_in_the_geometrys_own_coordinates():
    volume = far_quad().boundingVolume(None)
    assert np.asarray(volume.center) == pytest.approx((FAR, 0, 0), abs=1.0)
    assert np.asarray(volume.size) == pytest.approx((0, 0.02, 0.02), abs=1e-6)


def test_the_arrays_are_in_the_geometrys_own_coordinates():
    found = meshdata.geometry_arrays(far_quad())
    positions = np.asarray(found.attributes['POSITION'])
    assert positions[:, 0] == pytest.approx(FAR, abs=1.0)


def test_a_shape_answers_its_geometrys_origin():
    shape = basenodes.Shape(geometry=far_quad())
    assert shape.meshOrigin() == pytest.approx((FAR, 0, 0), abs=1e-9)
    assert basenodes.Shape(geometry=basenodes.Box()).meshOrigin() is None
    assert basenodes.Shape().meshOrigin() is None


def test_the_origin_follows_the_points():
    found = far_quad()
    found.mesh()
    found.coord.point = np.asarray(found.coord.point) + (10.0, 0, 0)
    assert found.meshOrigin() == pytest.approx((FAR + 10, 0, 0), abs=1e-9)


def test_a_geo_elevation_grid_without_an_origin_is_drawn_from_its_centre():
    grid = read('<Shape><GeoElevationGrid geoGridOrigin="45 10 0" xDimension="3" '
                'zDimension="3" xSpacing="0.00001" zSpacing="0.00001" '
                'height="0 0 0 0 1 0 0 0 0"/></Shape>').children[0].geometry
    assert np.linalg.norm(grid.meshOrigin()) > 6.3e6
    assert np.abs(grid.mesh().positions).max() < 2.0


SQUARE = ('<Shape><Appearance><UnlitMaterial emissiveColor="1 0 0"/></Appearance>'
          '<IndexedFaceSet solid="false" coordIndex="0 1 2 3"><GeoCoordinate point="'
          '44.99999865 9.9999981 0  44.99999865 10.0000019 0  45.00000135 10.0000019 0  '
          '45.00000135 9.9999981 0">%s</GeoCoordinate></IndexedFaceSet></Shape>')
VIEW = ('<NavigationInfo headlight="false"/><GeoViewpoint position="45 10 1" '
        'orientation="1 0 0 -1.5707963">%s</GeoViewpoint>')
ORIGIN = '<GeoOrigin containerField="geoOrigin" geoCoords="45 10 0"/>'


def drawn(origin):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read(VIEW % origin + SQUARE % origin)
    with scene_context(scene, size=(64, 64)) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)[:, :, 0] > 128


def test_a_square_far_from_the_scenes_origin_is_drawn_where_it_is(gl_context):
    """A 30 cm square a metre below the viewer, on the ellipsoid with no
    GeoOrigin, is drawn as it is with one at its own place"""
    exact = drawn(ORIGIN)
    assert 100 < exact.sum() < 64 * 64 - 100
    assert (drawn('') != exact).sum() <= 16
