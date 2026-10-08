"""X3D's pick sensors, told each frame what their picking geometry touches.

The events are pyvrml97's (``vrml.x3d.picking``); once a frame the pass tests
each sensor's ``pickingGeometry`` against the shapes under its ``pickTarget``
nodes (``OpenGLContext.scenegraph.x3dpicking``), in the sensor's coordinates.
"""
import numpy as np
import pytest
from vrml.x3d import picking

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import x3dpicking
from OpenGLContext.scenegraph.basenodes import (
    Box, Coordinate, IndexedLineSet, LineSet, PointSet, Sphere,
)


@pytest.mark.parametrize('name', ['LinePickSensor', 'PointPickSensor',
                                  'PrimitivePickSensor', 'VolumePickSensor'])
def test_each_is_pyvrml97s(name):
    assert issubclass(prototypes()[name], picking.PICK_SENSORS[name])


def test_an_indexed_line_sets_segments_run_along_each_polyline():
    lines = IndexedLineSet(coord=Coordinate(point=[(0, 0, 0), (0, 0, -2), (0, 3, -2), (5, 5, 5)]),
                           coordIndex=[0, 1, 2, -1, 3, 0])
    found = x3dpicking.line_segments(lines)
    assert np.allclose(found.starts, [(0, 0, 0), (0, 0, -2), (5, 5, 5)])
    assert np.allclose(found.ends, [(0, 0, -2), (0, 3, -2), (0, 0, 0)])
    assert np.allclose(found.along, [0, 2, 0])


def test_a_line_sets_segments_follow_its_vertex_counts():
    lines = LineSet(coord=Coordinate(point=[(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (0, 2, 0)]),
                    vertexCount=[3, 2])
    found = x3dpicking.line_segments(lines)
    assert len(found.starts) == 3
    assert np.allclose(found.along, [0, 1, 0])


def test_other_geometry_has_no_segments():
    assert x3dpicking.line_segments(Box()) is None
    assert x3dpicking.line_segments(IndexedLineSet()) is None


def test_a_point_sets_points():
    assert np.allclose(x3dpicking.points_of(PointSet(coord=Coordinate(point=[(1, 2, 3)]))),
                       [(1, 2, 3)])
    assert x3dpicking.points_of(Box()) is None


def test_the_primitives_are_solids():
    assert isinstance(x3dpicking.primitive_volume(Box(size=(2, 2, 2))), x3dpicking.pg.BoxVolume)
    assert isinstance(x3dpicking.primitive_volume(Sphere()), x3dpicking.pg.SphereVolume)
    assert x3dpicking.primitive_volume(PointSet()) is None


def document(body):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    return Loader.loads(b'<X3D version="4.0"><Scene>' + body + b'</Scene></X3D>', 'scene.x3d')


def drawn(scene, frames=2):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    with scene_context(scene) as context:
        for _ in range(frames):
            context.OnDraw(force=1)


TARGETS = b'''<Viewpoint position="0 0 20"/>
  <Group DEF="TARGETS">
    <Transform translation="0 0 -2"><Shape DEF="NEAR"><Box/></Shape></Transform>
    <Transform translation="0 0 -6"><Shape DEF="FAR"><Sphere/></Shape></Transform>
  </Group>'''


def line_sensor(attributes=b''):
    return (b'<LinePickSensor DEF="S" ' + attributes + b'''>
      <IndexedLineSet containerField="pickingGeometry" coordIndex="0 1">
        <Coordinate point="0.25 0.5 5  0.25 0.5 -10"/></IndexedLineSet>
      <Group USE="TARGETS" containerField="pickTarget"/>
    </LinePickSensor>''')


def test_a_line_picks_the_closest_surface_and_where_it_crossed(gl_context):
    scene = document(TARGETS + line_sensor(b'intersectionType="GEOMETRY"'))
    drawn(scene)
    sensor = scene.getDEF('S')
    assert sensor.isActive is True
    assert list(sensor.pickedGeometry) == [scene.getDEF('NEAR')]
    assert np.allclose(sensor.pickedPoint, [(0.25, 0.5, -1), (0.25, 0.5, -3)])
    assert np.allclose(sensor.pickedNormal, [(0, 0, 1), (0, 0, -1)], atol=1e-6)
    # The box's front face is textured left to right and bottom to top
    assert np.allclose(sensor.pickedTextureCoordinate[0], (0.625, 0.75, 0))


def test_a_line_picks_all_sorted_nearest_first(gl_context):
    scene = document(TARGETS + line_sensor(
        b'intersectionType="GEOMETRY" sortOrder="ALL_SORTED"'))
    drawn(scene)
    sensor = scene.getDEF('S')
    assert list(sensor.pickedGeometry) == [scene.getDEF('NEAR'), scene.getDEF('FAR')]
    assert len(sensor.pickedPoint) == 4
    assert sensor.pickedPoint[2][2] < sensor.pickedPoint[1][2]


def test_a_line_picking_bounds_enters_the_box(gl_context):
    scene = document(TARGETS + line_sensor(b'sortOrder="ALL"'))
    drawn(scene)
    sensor = scene.getDEF('S')
    assert list(sensor.pickedGeometry) == [scene.getDEF('NEAR'), scene.getDEF('FAR')]
    assert np.allclose(sensor.pickedPoint, [(0.25, 0.5, -1), (0.25, 0.5, -5)])
    assert np.allclose(sensor.pickedNormal, [(0, 0, 1), (0, 0, 1)])
    assert np.allclose(sensor.pickedTextureCoordinate, [(0.625, 0.75, 1), (0.625, 0.75, 1)])


def test_the_sensors_points_are_in_its_own_coordinates(gl_context):
    scene = document(TARGETS + b'<Transform translation="0 0 3">' + line_sensor(
        b'intersectionType="GEOMETRY"') + b'</Transform>')
    drawn(scene)
    assert np.allclose(scene.getDEF('S').pickedPoint, [(0.25, 0.5, -4), (0.25, 0.5, -6)])


def point_sensor(attributes, points):
    return (b'<PointPickSensor DEF="S" ' + attributes + b'''>
      <PointSet containerField="pickingGeometry"><Coordinate point="''' + points + b'''"/>
      </PointSet><Shape USE="FAR" containerField="pickTarget"/></PointPickSensor>''')


def test_a_point_in_the_spheres_bounds_but_not_the_sphere(gl_context):
    corner = b'0.8 0.8 -5.2  0 0 -6  5 5 5'
    scene = document(TARGETS + point_sensor(b'', corner))
    drawn(scene)
    assert np.allclose(scene.getDEF('S').pickedPoint, [(0.8, 0.8, -5.2), (0, 0, -6)])
    scene = document(TARGETS + point_sensor(b'intersectionType="GEOMETRY"', corner))
    drawn(scene)
    assert np.allclose(scene.getDEF('S').pickedPoint, [(0, 0, -6)])


def primitive_sensor(attributes=b'', where=b'0 0 0'):
    return (b'<Transform DEF="MOVE" translation="' + where + b'"><PrimitivePickSensor DEF="S" '
            + attributes + b'''><Sphere containerField="pickingGeometry" radius="0.5"/>
      <Group USE="TARGETS" containerField="pickTarget"/></PrimitivePickSensor></Transform>''')


def test_a_sphere_touching_a_box_picks_it_and_leaving_releases_it(gl_context):
    scene = document(TARGETS + primitive_sensor(b'intersectionType="GEOMETRY"', b'1.4 0 -2'))
    drawn(scene)
    sensor = scene.getDEF('S')
    assert sensor.isActive is True
    assert list(sensor.pickedGeometry) == [scene.getDEF('NEAR')]
    scene.getDEF('MOVE').translation = (1.4, 1.4, -2)   # the box's corner is 0.57 away
    drawn(scene, frames=1)
    assert sensor.isActive is False
    assert list(sensor.pickedGeometry) == []


def test_a_sphere_near_the_corner_meets_the_bounds(gl_context):
    scene = document(TARGETS + primitive_sensor(b'', b'1.4 1.4 -2'))
    drawn(scene)
    assert scene.getDEF('S').isActive is True


def test_a_volume_inside_a_target_picks_it(gl_context):
    scene = document(TARGETS + b'''<Transform translation="0 0 -6">
      <VolumePickSensor DEF="S" intersectionType="GEOMETRY">
        <Box containerField="pickingGeometry" size="0.2 0.2 0.2"/>
        <Group USE="TARGETS" containerField="pickTarget"/></VolumePickSensor></Transform>''')
    drawn(scene)
    assert list(scene.getDEF('S').pickedGeometry) == [scene.getDEF('FAR')]


def test_a_group_that_is_not_pickable_hides_its_shapes(gl_context):
    scene = document(b'''<PickableGroup DEF="G" pickable="false">
      <Shape DEF="IN"><Box/></Shape></PickableGroup>
      <PrimitivePickSensor DEF="S"><Box containerField="pickingGeometry"/>
        <PickableGroup USE="G" containerField="pickTarget"/></PrimitivePickSensor>''')
    drawn(scene)
    assert 'isActive' not in scene.getDEF('S').__dict__
    scene.getDEF('G').pickable = True
    drawn(scene, frames=1)
    assert scene.getDEF('S').isActive is True


def test_object_types_choose_which_groups_are_picked(gl_context):
    scene = document(b'''<Group DEF="ALLOF">
        <PickableGroup objectType='"DOOR"'><Shape DEF="DOOR"><Box/></Shape></PickableGroup>
        <PickableGroup objectType='"WALL"'><Shape DEF="WALL"><Box/></Shape></PickableGroup>
      </Group>
      <PrimitivePickSensor DEF="S" objectType='"WALL"' sortOrder="ALL">
        <Box containerField="pickingGeometry"/><Group USE="ALLOF" containerField="pickTarget"/>
      </PrimitivePickSensor>''')
    drawn(scene)
    assert list(scene.getDEF('S').pickedGeometry) == [scene.getDEF('WALL')]


def test_a_target_the_scene_does_not_draw_is_not_picked(gl_context):
    scene = document(b'''<Switch whichChoice="-1"><Shape DEF="HIDDEN"><Box/></Shape></Switch>
      <PrimitivePickSensor DEF="S"><Box containerField="pickingGeometry"/>
        <Shape USE="HIDDEN" containerField="pickTarget"/></PrimitivePickSensor>''')
    drawn(scene)
    assert 'isActive' not in scene.getDEF('S').__dict__


def test_a_disabled_sensor_releases_what_it_picked(gl_context):
    scene = document(TARGETS + primitive_sensor(b'', b'0 0 -2'))
    drawn(scene)
    sensor = scene.getDEF('S')
    assert sensor.isActive is True
    sensor.enabled = False
    drawn(scene, frames=1)
    assert sensor.isActive is False


def test_a_picked_routes_on(gl_context):
    scene = document(TARGETS + primitive_sensor(b'', b'0 0 -2') + b'''
      <BooleanFilter DEF="F"/>
      <ROUTE fromNode="S" fromField="isActive" toNode="F" toField="set_boolean"/>''')
    drawn(scene)
    assert scene.getDEF('F').inputTrue is True


def walked(*roots):
    """The paths a scene of `roots` has to each node, as the render pass keeps them"""
    from OpenGLContext.scenegraph.nodepath import NodePath  # noqa: PLC0415 kept with its use
    found = {}

    def walk(node, path):
        found.setdefault(node, []).append(path)
        children = getattr(node, 'renderedChildren', None)
        for child in (children() if children is not None else ()):
            walk(child, path + child)
    for root in roots:
        walk(root, NodePath([root]))
    return found


def sensed(sensor, *scene, place=None):
    """`sensor` placed by the Transform `place` (or at the root) told what it picks"""
    from OpenGLContext.scenegraph.basenodes import Transform  # noqa: PLC0415 kept with its use
    holder = place if place is not None else Transform()
    holder.children = [sensor]
    paths = walked(holder, *scene)
    x3dpicking.sense(paths[sensor], paths)
    return sensor


def cube_faces(size=1.0):
    from OpenGLContext.scenegraph.basenodes import IndexedFaceSet  # noqa: PLC0415 kept with its use
    h = size
    points = [(x, y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)]
    faces = [0, 1, 3, 2, -1, 4, 6, 7, 5, -1, 0, 4, 5, 1, -1, 2, 3, 7, 6, -1,
             0, 2, 6, 4, -1, 1, 5, 7, 3, -1]
    return IndexedFaceSet(coord=Coordinate(point=points), coordIndex=faces, solid=False)


def shape(geometry, translation=(0, 0, 0)):
    from OpenGLContext.scenegraph.basenodes import Shape, Transform  # noqa: PLC0415 kept with its use
    found = Shape(geometry=geometry)
    return found, Transform(translation=translation, children=[found])


@pytest.mark.parametrize('primitive', ['Cylinder', 'Cone'])
def test_a_cylinder_or_cone_picks_by_its_solid(primitive):
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 kept with its use
    target, placed = shape(Box(), (1.6, 0, 0))
    sensor = picking.PrimitivePickSensor(pickingGeometry=getattr(basenodes, primitive)(),
                                         pickTarget=[placed], intersectionType='GEOMETRY')
    sensed(sensor, placed)
    assert list(sensor.pickedGeometry) == [target]
    placed.translation = (0, 0, 2.2)
    sensed(sensor, placed)
    assert list(sensor.pickedGeometry) == []


def test_a_volume_of_faces_picks_what_it_reaches():
    target, placed = shape(Sphere(radius=0.5), (1.2, 0, 0))
    sensor = picking.VolumePickSensor(pickingGeometry=cube_faces(), pickTarget=[placed],
                                      intersectionType='GEOMETRY')
    assert list(sensed(sensor, placed).pickedGeometry) == [target]


def test_a_crossing_reports_the_surfaces_own_texture_coordinate():
    from OpenGLContext.scenegraph.basenodes import TriangleSet  # noqa: PLC0415 kept with its use
    # X3D maps a set without coordinates across its bounding box
    triangle = TriangleSet(coord=Coordinate(point=[(-1, -1, 0), (1, -1, 0), (0, 1, 0)]))
    _target, placed = shape(triangle)
    line = IndexedLineSet(coord=Coordinate(point=[(0, 0, 1), (0, 0, -1)]), coordIndex=[0, 1])
    sensor = picking.LinePickSensor(pickingGeometry=line, pickTarget=[placed],
                                    intersectionType='GEOMETRY')
    sensed(sensor, placed)
    assert np.allclose(sensor.pickedPoint, [(0, 0, 0)])
    assert np.allclose(sensor.pickedTextureCoordinate, [(0.5, 0.5, 0)])


class Untextured:
    """A geometry whose triangles carry no texture coordinates"""

    def boundingVolume(self, mode):
        return Box(size=(2, 2, 0.01)).boundingVolume(mode)

    def meshArrays(self):
        from OpenGLContext.scenegraph import meshdata  # noqa: PLC0415 kept with its use
        return meshdata.arrays([(-1, -1, 0), (1, -1, 0), (0, 1, 0)], None)


def test_a_surface_without_texture_coordinates_gives_zeros():
    target = x3dpicking.Target(type('S', (), {'geometry': Untextured()})(), None, np.identity(4))
    segments = x3dpicking.Segments(np.array([(0.0, 0, 1)]), np.array([(0.0, 0, -1)]), np.zeros(1))
    found = x3dpicking._line_pick(target, segments, True)
    assert np.allclose(found.points, [(0, 0, 0)])
    assert np.allclose(found.texCoords, [(0, 0, 0)])


@pytest.mark.parametrize('kind, picker', [
    (picking.LinePickSensor, IndexedLineSet(coord=Coordinate(point=[(0, 0, 3), (0, 0, -3)]),
                                            coordIndex=[0, 1])),
    (picking.PointPickSensor, PointSet(coord=Coordinate(point=[(0, 0, 0)]))),
    (picking.VolumePickSensor, Box().__class__(size=(1, 1, 1))),
])
def test_geometry_without_triangles_is_not_picked_by_its_surface(kind, picker):
    lines = IndexedLineSet(coord=Coordinate(point=[(0, -1, 0), (0, 1, 0)]), coordIndex=[0, 1])
    _target, placed = shape(lines)
    sensor = kind(pickingGeometry=picker, pickTarget=[placed], intersectionType='GEOMETRY')
    sensed(sensor, placed)
    assert 'isActive' not in sensor.__dict__


@pytest.mark.parametrize('kind, picker', [
    (picking.LinePickSensor, Box()),
    (picking.PointPickSensor, Box()),
    (picking.PrimitivePickSensor, PointSet(coord=Coordinate(point=[(0, 0, 0)]))),
    (picking.VolumePickSensor, PointSet(coord=Coordinate(point=[(0, 0, 0)]))),
    (picking.VolumePickSensor, None),
])
def test_a_picking_geometry_of_the_wrong_kind_picks_nothing(kind, picker):
    _target, placed = shape(Box())
    sensor = kind(pickTarget=[placed])
    if picker is not None:
        sensor.pickingGeometry = picker
    sensed(sensor, placed)
    assert 'isActive' not in sensor.__dict__


def test_a_sensor_scaled_to_nothing_picks_nothing():
    from OpenGLContext.scenegraph.basenodes import Transform  # noqa: PLC0415 kept with its use
    _target, placed = shape(Box())
    sensor = picking.PrimitivePickSensor(pickingGeometry=Box(), pickTarget=[placed])
    sensed(sensor, placed, place=Transform(scale=(0, 0, 0)))
    assert 'isActive' not in sensor.__dict__


def test_targets_not_drawn_or_broken_or_null_are_passed_over():
    _target, placed = shape(Box())
    loose = shape(Box())[1]
    sensor = picking.PrimitivePickSensor(pickingGeometry=Box(), pickTarget=[placed, loose])
    paths = walked(placed)
    for path in paths[placed]:
        path.broken = True
    assert list(x3dpicking.targets(sensor, paths, np.identity(4))) == []


def test_a_target_without_bounds_is_not_picked():
    class Unbounded:
        PROTO = 'Unbounded'

        def boundingVolume(self, mode):
            raise ValueError('no bounds')
    target = x3dpicking.Target(object(), None, np.identity(4))
    target = target._replace(shape=type('S', (), {'geometry': Unbounded()})())
    segments = x3dpicking.Segments(np.zeros((1, 3)), np.ones((1, 3)), np.zeros(1))
    assert x3dpicking._line_pick(target, segments, False) is None
    assert x3dpicking._point_pick(target, np.zeros((1, 3)), False) is None
    assert x3dpicking._volume_pick(target, x3dpicking.pg.SphereVolume(1.0), False) is None


def test_lines_of_fewer_than_two_points_are_no_segments():
    points = Coordinate(point=[(0, 0, 0), (1, 0, 0)])
    assert x3dpicking.line_segments(IndexedLineSet(coord=points, coordIndex=[0, -1, 1, 9])) is None
    assert x3dpicking.line_segments(LineSet(coord=points, vertexCount=[1, 1])) is None


class Bounded:
    """A geometry with the bounding volume corners and triangles it is given"""

    PROTO = 'Bounded'

    def __init__(self, corners, triangles=None):
        self.corners, self.triangles = corners, triangles

    def boundingVolume(self, mode):
        return type('V', (), {'getPoints': lambda volume: self.corners})()

    def meshArrays(self):
        return self.triangles


def held(geometry):
    return x3dpicking.Target(type('S', (), {'geometry': geometry})(), None, np.identity(4))


@pytest.mark.parametrize('corners', [None, [], [(np.inf, 0, 0, 1), (0, 0, 0, 1)]])
def test_bounds_that_are_missing_or_unbounded_pick_nothing(corners):
    assert x3dpicking._volume_pick(held(Bounded(corners)), x3dpicking.pg.SphereVolume(1.0),
                                   False) is None


def test_a_mesh_of_fewer_than_three_corners_has_no_triangles():
    from OpenGLContext.scenegraph.composedgeometry import ComposedArrays  # noqa: PLC0415 kept with its use
    arrays = ComposedArrays(attributes={'POSITION': np.zeros((2, 3), 'f'),
                                        'NORMAL': np.zeros((2, 3), 'f')},
                            indices=np.array([0, 1], dtype=np.uint32))
    box = [(-1, -1, -1, 1), (1, 1, 1, 1)]
    assert x3dpicking._point_pick(held(Bounded(box, arrays)), np.zeros((1, 3)), True) is None


def test_a_line_through_the_bounds_that_misses_the_surface_picks_nothing():
    target = held(Untextured())
    segments = x3dpicking.Segments(np.array([(0.9, 0.9, 1)]), np.array([(0.9, 0.9, -1)]),
                                   np.zeros(1))
    assert x3dpicking._line_pick(target, segments, True) is None


def test_a_point_set_has_no_segments_and_a_null_target_is_passed_over():
    assert x3dpicking.line_segments(PointSet(coord=Coordinate(point=[(0, 0, 0)]))) is None
    sensor = picking.PrimitivePickSensor(pickingGeometry=Box())
    sensor.__dict__['pickTarget'] = [None]
    assert list(x3dpicking.targets(sensor, {}, np.identity(4))) == []


def test_bounds_reached_with_no_triangles_behind_them_pick_nothing():
    target = held(Bounded([(-1, -1, -1, 1), (1, 1, 1, 1)]))
    segments = x3dpicking.Segments(np.array([(0.0, 0, 5)]), np.array([(0.0, 0, -5)]), np.zeros(1))
    assert x3dpicking._line_pick(target, segments, True) is None
    assert x3dpicking._point_pick(target, np.zeros((1, 3)), True) is None


def test_what_misses_the_bounds_is_not_picked():
    target = held(Bounded([(-1, -1, -1, 1), (1, 1, 1, 1)]))
    segments = x3dpicking.Segments(np.array([(5.0, 0, 5)]), np.array([(5.0, 0, -5)]), np.zeros(1))
    assert x3dpicking._line_pick(target, segments, False) is None
    assert x3dpicking._point_pick(target, np.full((1, 3), 5.0), False) is None
