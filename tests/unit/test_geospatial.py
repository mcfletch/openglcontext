"""Tests for the Geospatial component: nodes placed on the Earth

Frames and coordinates are vrml.x3d.geospatial's, in double precision; here
the engine's nodes are held to them and drawn.
"""
import numpy as np
import pytest
from vrml.x3d import geospatial as frames

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes, coordinates, nodepath
from OpenGLContext.testing.memo import check_memo_inputs

WGS84_A = 6378137.0


def read(body, version='4.0'):
    return Loader.loads(('<X3D version="%s"><Scene>%s</Scene></X3D>' % (version, body)).encode(),
                        'scene.x3d')


def path_to(scene, *nodes):
    found = nodepath.NodePath([]) + scene
    for node in nodes:
        found = found + node
    return found


def test_a_geo_location_places_its_children_on_the_ellipsoid():
    scene = read('<GeoLocation geoCoords="0 0 0"><Shape><Box/></Shape></GeoLocation>')
    location = scene.children[0]
    matrix = np.asarray(path_to(scene, location, location.children[0]).transformMatrix())
    assert matrix[3, :3] == pytest.approx((WGS84_A, 0, 0), abs=1e-6)
    assert matrix[1, :3] == pytest.approx((1, 0, 0))     # +Y up
    assert matrix[2, :3] == pytest.approx((0, 0, -1))    # -Z north


def test_its_matrix_is_double_precision():
    scene = read('<GeoLocation geoCoords="45.0000001 7 3.25"/>')
    location = scene.children[0]
    expected = frames.location_matrix(frames.system(['GD']), (45.0000001, 7, 3.25))
    assert np.asarray(location.localMatrix()) == pytest.approx(expected, abs=1e-6)


def test_a_geo_origin_is_subtracted():
    scene = read('<GeoLocation geoCoords="0 0 10"><GeoOrigin containerField="geoOrigin" '
                 'geoCoords="0 0 0"/></GeoLocation>')
    assert np.asarray(scene.children[0].localMatrix())[3, :3] == pytest.approx((10, 0, 0),
                                                                                  abs=1e-6)


def test_rotate_y_up_makes_the_origins_up_the_scenes():
    scene = read('<GeoLocation geoCoords="45 10 5"><GeoOrigin containerField="geoOrigin" '
                 'geoCoords="45 10 0" rotateYUp="true"/></GeoLocation>')
    matrix = np.asarray(scene.children[0].localMatrix())
    assert matrix[3, :3] == pytest.approx((0, 5, 0), abs=1e-6)
    assert matrix[1, :3] == pytest.approx((0, 1, 0), abs=1e-9)


def test_utm_coordinates_place_the_same_point():
    gd = read('<GeoLocation geoCoords="43.6532 -79.3832 76"/>').children[0]
    northing, easting, height = frames.from_geocentric(
        frames.system(['UTM', 'Z17']), frames.to_geocentric(frames.system(['GD']),
                                                            [(43.6532, -79.3832, 76)]))[0]
    utm = read('<GeoLocation geoSystem=\'"UTM" "Z17"\' geoCoords="%r %r %r"/>'
               % (float(northing), float(easting), float(height))).children[0]
    assert np.asarray(utm.localMatrix()) == pytest.approx(np.asarray(gd.localMatrix()),
                                                          abs=1e-5)


def test_a_geo_transform_turns_about_its_centre():
    """A quarter turn about the local up at a point leaves the point where it is"""
    scene = read('<GeoTransform geoCenter="0 0 0" rotation="0 1 0 1.5707963"/>')
    transform = scene.children[0]
    centre = np.array([WGS84_A, 0.0, 0.0, 1.0])
    assert centre @ np.asarray(transform.localMatrix()) == pytest.approx(centre, abs=1e-5)
    # A point a metre east of the centre moves a metre north (to -Z local, +Z geocentric)
    east = np.array([WGS84_A, 1.0, 0.0, 1.0])
    moved = east @ np.asarray(transform.localMatrix())
    assert moved[:3] == pytest.approx((WGS84_A, 0.0, 1.0), abs=1e-5)


def test_the_frame_follows_its_fields_and_its_origin():
    scene = read('<GeoLocation geoCoords="0 0 0"><GeoOrigin containerField="geoOrigin" '
                 'geoCoords="0 0 0"/></GeoLocation>')
    location = scene.children[0]
    origin = location.geoOrigin
    check_memo_inputs(
        lambda: np.asarray(location.localMatrix()).copy(),
        [('geoCoords', lambda: setattr(location, 'geoCoords', (0, 0, 7))),
         ('origin geoCoords', lambda: setattr(origin, 'geoCoords', (0, 0, 2))),
         ('rotateYUp', lambda: setattr(origin, 'rotateYUp', True))],
        fresh=location.geoMatrix)


def test_bounds_are_its_childrens_in_the_frame():
    scene = read('<GeoLocation geoCoords="0 0 0"><GeoOrigin containerField="geoOrigin" '
                 'geoCoords="0 0 0"/><Shape><Box size="2 2 2"/></Shape></GeoLocation>')
    points = scene.children[0].boundingVolume(None).getPoints()[:, :3]
    assert points.min(axis=0) == pytest.approx((-1, -1, -1), abs=1e-6)


def test_a_geo_location_draws_where_it_is(gl_context):
    """A box on the Earth's surface, seen from a metre above it"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read('<NavigationInfo headlight="false"/>'
                 '<GeoLocation geoCoords="0 0 0"><Shape><Appearance><UnlitMaterial '
                 'emissiveColor="1 0 0"/></Appearance><Box size="0.2 0.2 0.2"/></Shape>'
                 '</GeoLocation>')
    with scene_context(scene, size=(48, 48)) as context:
        context.platform.setPosition((WGS84_A + 2.0, 0.0, 0.0))
        context.platform.setOrientation((0, 1, 0, np.pi / 2))     # looking along -X
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert image[24, 24, 0] > 200


GEO_TRIANGLE = ('<IndexedTriangleSet index="0 1 2"><GeoCoordinate point="0 0 0 0 0.001 0 '
                '0.001 0 0"><GeoOrigin containerField="geoOrigin" geoCoords="0 0 0"/>'
                '</GeoCoordinate></IndexedTriangleSet>')


def test_geo_coordinate_points_are_in_the_scene():
    coord = read('<Shape>%s</Shape>' % GEO_TRIANGLE).children[0].geometry.coord
    points = coordinates.points(coord)
    expected = frames.scene_points(coord, [(0, 0, 0), (0, 0.001, 0), (0.001, 0, 0)])
    assert points == pytest.approx(expected, abs=1e-9)
    assert points[1][1] == pytest.approx(111.32, abs=0.01)   # a thousandth of a degree east


def test_plain_coordinates_are_their_points():
    coord = basenodes.Coordinate(point=[(1, 2, 3)])
    assert np.asarray(coordinates.points(coord)) == pytest.approx(np.array([(1, 2, 3)]))
    assert coordinates.points(None) is None


def test_geo_coordinate_points_follow_their_fields_and_origin():
    coord = read('<Shape>%s</Shape>' % GEO_TRIANGLE).children[0].geometry.coord
    origin = coord.geoOrigin
    check_memo_inputs(
        lambda: np.asarray(coord.scenePoints()).copy(),
        [('point', lambda: setattr(coord, 'point', [(0, 0, 5)] * 3)),
         ('origin geoCoords', lambda: setattr(origin, 'geoCoords', (0, 0, 2))),
         ('rotateYUp', lambda: setattr(origin, 'rotateYUp', True)),
         ('geoSystem', lambda: setattr(coord, 'geoSystem', ['GC']))])


@pytest.mark.parametrize('geometry', [
    GEO_TRIANGLE,
    GEO_TRIANGLE.replace('IndexedTriangleSet index', 'IndexedFaceSet coordIndex')
                .replace('IndexedTriangleSet', 'IndexedFaceSet'),
    GEO_TRIANGLE.replace('<IndexedTriangleSet index="0 1 2">', '<TriangleSet>')
                .replace('</IndexedTriangleSet>', '</TriangleSet>'),
    GEO_TRIANGLE.replace('IndexedTriangleSet index="0 1 2"', 'PointSet')
                .replace('IndexedTriangleSet', 'PointSet'),
    GEO_TRIANGLE.replace('IndexedTriangleSet index="0 1 2"', 'IndexedLineSet coordIndex="0 1 2"')
                .replace('IndexedTriangleSet', 'IndexedLineSet'),
])
def test_geometry_on_geo_coordinates_is_bounded_in_the_scene(geometry):
    shape = read('<Shape>%s</Shape>' % geometry).children[0]
    points = shape.geometry.boundingVolume(None).getPoints()[:, :3]
    assert points.max(axis=0)[1] == pytest.approx(111.32, abs=0.01)


def test_colliders_and_mirrors_read_geo_coordinates_in_the_scene():
    from OpenGLContext.passes.reflection import _geometry_points  # noqa: PLC0415 private reader
    from OpenGLContext.physics.gltf_world import _mesh_positions_indices  # noqa: PLC0415 private reader
    geometry = read('<Shape>%s</Shape>' % GEO_TRIANGLE.replace(
        'IndexedTriangleSet index', 'IndexedFaceSet coordIndex').replace(
        'IndexedTriangleSet', 'IndexedFaceSet')).children[0].geometry
    assert _mesh_positions_indices(geometry)[0][1][1] == pytest.approx(111.32, abs=0.01)
    assert _geometry_points(geometry)[0][1][1] == pytest.approx(111.32, abs=0.01)


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_geo_coordinate_geometry_draws_where_it_is(gl_context, renderer):
    """A two-metre square on the equator, seen from five metres above"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read('<NavigationInfo headlight="false"/>'
                 '<Viewpoint position="0 5 0" orientation="1 0 0 -1.5707963"/>'
                 '<Shape><Appearance><Material diffuseColor="0 0 0" emissiveColor="1 0 0"/>'
                 '</Appearance><IndexedFaceSet solid="false" coordIndex="0 1 2 3"><GeoCoordinate '
                 'point="-0.00001 -0.00001 0 -0.00001 0.00001 0 0.00001 0.00001 0 '
                 '0.00001 -0.00001 0"><GeoOrigin containerField="geoOrigin" geoCoords="0 0 0" '
                 'rotateYUp="true"/></GeoCoordinate></IndexedFaceSet></Shape>')
    with scene_context(scene, size=(48, 48), renderer=renderer) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert image[24, 24, 0] > 200
    assert image[2, 2, 0] < 50


GEO_GRID = ('<GeoElevationGrid geoGridOrigin="-0.00001 -0.00001 0" xDimension="3" zDimension="3" '
            'xSpacing="0.00001" zSpacing="0.00001" height="0 0 0 0 %s 0 0 0 0" solid="true">'
            '<GeoOrigin containerField="geoOrigin" geoCoords="0 0 0" rotateYUp="true"/>'
            '</GeoElevationGrid>')


def test_a_geo_elevation_grid_rises_along_the_local_up():
    grid = read('<Shape>%s</Shape>' % (GEO_GRID % 3)).children[0].geometry
    points = grid.boundingVolume(None).getPoints()[:, :3]
    assert points.max(axis=0) == pytest.approx((1.113, 3, 1.106), abs=0.01)
    assert points.min(axis=0)[1] == pytest.approx(0, abs=1e-3)
    assert (np.asarray(grid.meshArrays().attributes['NORMAL'])[:, 1] > 0).all()


def test_a_geo_elevation_grid_follows_its_fields_and_origin():
    grid = read('<Shape>%s</Shape>' % (GEO_GRID % 3)).children[0].geometry
    origin = grid.geoOrigin
    check_memo_inputs(
        lambda: np.asarray(grid.meshArrays().attributes['POSITION']).copy(),
        [('height', lambda: setattr(grid, 'height', [0, 0, 0, 0, 7, 0, 0, 0, 0])),
         ('yScale', lambda: setattr(grid, 'yScale', 2.0)),
         ('origin geoCoords', lambda: setattr(origin, 'geoCoords', (0, 0, 2))),
         ('rotateYUp', lambda: setattr(origin, 'rotateYUp', False))])


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_geo_elevation_grid_faces_up(gl_context, renderer):
    """Solid, seen from above, a flat grid on the equator is drawn"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read('<NavigationInfo headlight="false"/>'
                 '<Viewpoint position="0 5 0" orientation="1 0 0 -1.5707963"/>'
                 '<Shape><Appearance><Material diffuseColor="0 0 0" emissiveColor="1 0 0"/>'
                 '</Appearance>%s</Shape>' % (GEO_GRID % 0))
    with scene_context(scene, size=(48, 48), renderer=renderer) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert image[24, 24, 0] > 200
    assert image[2, 2, 0] < 50


GEO_VIEW = ('<GeoViewpoint position="0 0 100" centerOfRotation="0 0 0" speedFactor="2">'
            '<GeoOrigin containerField="geoOrigin" geoCoords="0 0 0"/></GeoViewpoint>')


def test_a_geo_viewpoint_is_placed_at_its_position():
    """Its orientation is held by the drawn cases below"""
    view = read(GEO_VIEW).children[0]
    position, _ = view.placement()
    assert np.asarray(position) == pytest.approx((100, 0, 0), abs=1e-6)
    assert np.asarray(view.localCentre()) == pytest.approx((0, 0, 0), abs=1e-6)


def test_a_geo_viewpoint_speeds_up_with_elevation():
    view = read(GEO_VIEW).children[0]
    assert view.speedScale((100, 0, 0)) == pytest.approx(2 * 110 / 10)
    assert view.speedScale((-50, 0, 0)) == pytest.approx(2.0)


def test_a_plain_viewpoint_places_by_its_fields():
    view = basenodes.Viewpoint(position=(1, 2, 3), orientation=(0, 1, 0, 0.5))
    position, orientation = view.placement()
    assert tuple(position) == (1, 2, 3)
    assert orientation.XYZR()[3] == pytest.approx(0.5)
    assert view.speedScale((0, 0, 0)) == 1.0


def test_a_bound_geo_viewpoint_places_the_camera(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read(GEO_VIEW)
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        position = np.asarray(context.platform.position, 'd')[:3]
    assert position == pytest.approx((100, 0, 0), abs=1e-4)


@pytest.mark.parametrize('box, orientation', [
    ('0.0001 0 0', '0 0 1 0'),             # north, looking north
    ('0 0.0001 0', '0 1 0 -1.5707963'),    # east, turned right to face east
    ('0 -0.0001 0', '0 1 0 1.5707963'),    # west, turned left
    ('0 0 30', '1 0 0 1.5707963'),         # overhead, looking up
])
def test_a_geo_viewpoint_looks_the_way_it_is_turned(gl_context, box, orientation):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read('<NavigationInfo headlight="false"/>'
                 '<GeoViewpoint position="0 0 2" orientation="%s"><GeoOrigin '
                 'containerField="geoOrigin" geoCoords="0 0 0"/></GeoViewpoint>'
                 '<GeoLocation geoCoords="%s"><GeoOrigin containerField="geoOrigin" '
                 'geoCoords="0 0 0"/><Shape><Appearance><Material diffuseColor="0 0 0" '
                 'emissiveColor="1 0 0"/></Appearance><Box size="4 4 4"/></Shape>'
                 '</GeoLocation>' % (orientation, box))
    with scene_context(scene, size=(48, 48)) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    assert image[24, 24, 0] > 200


def test_a_bound_geo_viewpoint_scales_navigation(gl_context):
    from OpenGLContext.passes import viewpointbinding  # noqa: PLC0415 imports GL
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(read(GEO_VIEW), size=(32, 32)) as context:
        drawn_image(context)
        assert viewpointbinding.speed_scale(context) == pytest.approx(2 * 110 / 10, rel=1e-4)


GEO_LOD = ('<GeoLOD center="0 0 0" range="1000" child1Url="near.x3d"><GeoOrigin '
           'containerField="geoOrigin" geoCoords="0 0 0"/><Shape containerField="rootNode">'
           '<Box/></Shape></GeoLOD>')


def test_a_geo_lod_far_away_draws_its_root():
    node = read(GEO_LOD).children[0]
    node.selectAt(5000.0, 1.0, 1.0)
    assert node.level_changed == 0
    drawn = node.renderedChildren()
    assert len(drawn) == 1 and drawn[0].children[0] is node.rootNode[0]
    assert 'children' not in node.__dict__


def test_a_geo_lod_close_by_reads_its_children():
    node = read(GEO_LOD).children[0]
    node.selectAt(5000.0, 1.0, 1.0)
    node.selectAt(10.0, 1.0, 1.0)
    assert node.level_changed == 1
    assert [list(child.url) for child in node.children] == [['near.x3d']]
    assert node.renderedChildren()[0].children == node.children


def test_a_geo_lods_children_are_not_read_until_it_is_close():
    node = read(GEO_LOD).children[0]
    node.selectAt(5000.0, 1.0, 1.0)
    assert not node.levelNodes()[0].children


def test_a_geo_lods_distance_is_measured_to_its_centre_in_the_scene():
    node = read(GEO_LOD.replace('center="0 0 0"', 'center="0 0 25"')).children[0]
    assert np.asarray(node.distanceCentre()) == pytest.approx((25, 0, 0), abs=1e-6)


def test_a_geo_lod_is_chosen_by_the_pass(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = read('<Viewpoint position="0 0 10"/>' + GEO_LOD.replace(
        'geoCoords="0 0 0"/>', 'geoCoords="0 0 0" rotateYUp="true"/>'))
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
    assert scene.children[1].level_changed == 1


def test_a_geo_lod_left_sends_no_children():
    node = read(GEO_LOD).children[0]
    node.selectAt(10.0, 1.0, 1.0)
    node.selectAt(5000.0, 1.0, 1.0)
    assert node.level_changed == 0
    assert list(node.children) == []


def test_a_geo_lods_centre_follows_its_fields_and_origin():
    node = read(GEO_LOD).children[0]
    origin = node.geoOrigin
    check_memo_inputs(
        lambda: np.asarray(node.distanceCentre()).copy(),
        [('center', lambda: setattr(node, 'center', (0, 0, 9))),
         ('origin geoCoords', lambda: setattr(origin, 'geoCoords', (0, 0, 2))),
         ('rotateYUp', lambda: setattr(origin, 'rotateYUp', True)),
         ('geoSystem', lambda: setattr(node, 'geoSystem', ['GC']))])
