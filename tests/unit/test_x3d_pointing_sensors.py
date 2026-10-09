"""The pointing-device sensors, told of each context's pointer.

The behaviour is pyvrml97's (``vrml.x3d.pointing``). A context's picked
pointer events reach ``OpenGLContext.scenegraph.x3dpointing.PointerSensing``,
which finds the sensors beside the geometry under the pointer -- those of the
lowest group on the picked path that has any -- and tells them the hit and
the pointer's ray in their own coordinates.
"""
import numpy as np
import pytest
from vrml.x3d import geospatial, pointing

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.scenegraph import nodepath, x3dpointing
from OpenGLContext.scenegraph.basenodes import Box, Group, Shape, Transform, sceneGraph


@pytest.mark.parametrize('name', ['TouchSensor', 'PlaneSensor', 'CylinderSensor', 'SphereSensor',
                                  'GeoTouchSensor'])
def test_each_is_the_engines(name):
    found = prototypes()[name]
    assert issubclass(found, pointing.POINTING[name])
    assert hasattr(found, 'bind')


class Camera:
    """A platform's matrices and a viewport, as a picked event carries them"""

    def __init__(self, position=(0, 0, 10)):
        platform = ViewPlatform(position=position, aspect=1.0, near=1.0, far=100.0)
        self.modelViewMatrix = platform.modelMatrix()
        self.projectionMatrix = platform.viewMatrix()
        self.viewport = (0, 0, 100, 100)


def test_the_ray_through_the_middle_of_the_view_looks_ahead():
    origin, direction = x3dpointing.pointer_ray(Camera(), 50, 50)
    assert origin == pytest.approx((0, 0, 9), abs=1e-4)
    assert direction / np.linalg.norm(direction) == pytest.approx((0, 0, -1), abs=1e-6)


def test_the_ray_looks_ahead_through_the_render_passes_trimmed_projection():
    # The pass trims the projection with a negative depth, which puts the far
    # plane behind the camera: depth 1 is not in front of it
    camera = Camera()
    camera.projectionMatrix = ViewPlatform(aspect=1.0, near=1.0).viewMatrix(-(101 * 1.01))
    _origin, direction = x3dpointing.pointer_ray(camera, 50, 50)
    assert direction / np.linalg.norm(direction) == pytest.approx((0, 0, -1), abs=1e-6)


def test_a_depth_unprojects_to_the_world():
    camera = Camera()
    # Depth of a point 5 units in front of the camera, in [0, 1].
    clip = np.array([0, 0, 5, 1.0]) @ camera.modelViewMatrix @ camera.projectionMatrix
    depth = (clip[2] / clip[3] + 1) / 2
    assert x3dpointing.unprojected(camera, 50, 50, depth) == pytest.approx((0, 0, 5), abs=1e-3)


def scene():
    touch = x3dpointing.TouchSensor()
    shape = Shape(geometry=Box())
    inner = Transform(translation=(2, 0, 0), children=[shape, touch])
    outer = Group(children=[inner, x3dpointing.TouchSensor()])
    graph = sceneGraph(children=[outer])
    path = nodepath.NodePath([]) + graph + outer + inner + shape
    return graph, path, touch


def test_the_sensors_are_those_of_the_lowest_group_with_any():
    _graph, path, touch = scene()
    sensors, prefix = x3dpointing.sensors_for(path)
    assert sensors == [touch]
    assert prefix[-1] is path[-2]


def test_a_disabled_sensor_leaves_it_to_the_group_above():
    _graph, path, touch = scene()
    touch.enabled = False
    sensors, prefix = x3dpointing.sensors_for(path)
    assert len(sensors) == 1 and sensors[0] is not touch
    assert prefix[-1] is path[1]


def test_no_sensors_on_the_path():
    graph = sceneGraph(children=[Shape(geometry=Box())])
    path = nodepath.NodePath([]) + graph + graph.children[0]
    assert x3dpointing.sensors_for(path) == ([], None)


class Event(Camera):
    def __init__(self, kind, path, x=50, y=50, depth=None, button=0, state=1):
        super().__init__()
        self.type = kind
        self.button, self.state = button, state
        self.pickPoint = (x, y)
        self.objectPaths = [path if path is not None else []]
        self.viewCoordinate = (x, y, depth) if depth is not None else ()
        self.stopPropagation = 0

    def getObjectPaths(self):
        return self.objectPaths

    def getPickPoint(self):
        return self.pickPoint


def depth_at(distance):
    camera = Camera()
    clip = np.array([0, 0, 10 - distance, 1.0]) @ camera.modelViewMatrix @ camera.projectionMatrix
    return (clip[2] / clip[3] + 1) / 2


def test_a_click_on_the_geometry_touches_its_sensor():
    _graph, path, touch = scene()
    sensing = x3dpointing.PointerSensing()
    hit = depth_at(9.0)
    sensing.observe(Event('mousemove', path, depth=hit))
    assert touch.isOver is True
    assert tuple(touch.hitPoint_changed) == pytest.approx((-2, 0, 1), abs=1e-3)
    press = Event('mousebutton', path, depth=hit, state=1)
    sensing.observe(press)
    assert touch.isActive is True
    assert not press.stopPropagation
    sensing.observe(Event('mousebutton', path, depth=hit, state=0))
    assert touch.isActive is False
    assert 'touchTime' in touch.__dict__


def test_moving_off_the_geometry_ends_isover():
    _graph, path, touch = scene()
    sensing = x3dpointing.PointerSensing()
    sensing.observe(Event('mousemove', path, depth=depth_at(9.0)))
    sensing.observe(Event('mousemove', None))
    assert touch.isOver is False


def test_other_buttons_leave_the_sensors_alone():
    _graph, path, touch = scene()
    sensing = x3dpointing.PointerSensing()
    sensing.observe(Event('mousebutton', path, depth=depth_at(9.0), button=1))
    assert 'isActive' not in touch.__dict__


def test_a_plane_sensor_drags_off_its_geometry():
    plane = x3dpointing.PlaneSensor()
    shape = Shape(geometry=Box())
    group = Group(children=[shape, plane])
    graph = sceneGraph(children=[group])
    path = nodepath.NodePath([]) + graph + group + shape
    sensing = x3dpointing.PointerSensing()
    sensing.observe(Event('mousebutton', path, depth=depth_at(9.0)))
    moved = Event('mousemove', None, x=75)
    moved.modelViewMatrix = moved.projectionMatrix = None
    sensing.observe(moved)
    translation = plane.translation_changed
    assert translation[0] > 0.1
    assert translation[1:] == pytest.approx((0, 0), abs=1e-6)
    sensing.observe(Event('mousebutton', None, state=0))
    assert plane.isActive is False


def test_observers_count_as_mouse_move_handlers():
    from OpenGLContext.context import ContextCore  # noqa: PLC0415 kept with its use

    class Watching:
        def __init__(self):
            self.observed = {'mousemove': [print]}

        def isCapturingEvents(self, kind):
            return False

        def getEventManager(self, kind):
            return None

        def observersOf(self, kind):
            return self.observed.get(kind, [])

    assert ContextCore.hasMouseMoveHandlers(Watching())


def test_a_documents_touch_sensor_is_clicked(gl_context):
    from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Viewpoint position="0 0 5"/>
      <Group><Shape><Box size="3 3 3"/></Shape><TouchSensor DEF="T"/></Group>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(64, 64)) as context:
        context.OnDraw(force=1)
        for record in (
            {'type': 'mousemove', 'buttons': [], 'x': 32, 'y': 32, 'pick': True},
            {'type': 'mousebutton', 'button': 0, 'state': 1, 'x': 32, 'y': 32, 'pick': True},
            {'type': 'mousebutton', 'button': 0, 'state': 0, 'x': 32, 'y': 32, 'pick': True},
        ):
            synthetic.dispatch(context, record)
            context.OnDraw(force=1)
        # A pick is read back once its fence signals: a frame or two after
        # it is drawn on an idle machine, more on a busy one.
        touch = scene.getDEF('T')
        for _ in range(120):
            if 'touchTime' in touch.__dict__:
                break
            context.OnDraw(force=1)
    assert touch.isOver is True
    assert tuple(touch.hitPoint_changed)[2] == pytest.approx(1.5, abs=0.05)
    assert 'touchTime' in touch.__dict__


def test_a_documents_geo_touch_sensor_sends_the_hit_in_its_geo_system(gl_context):
    from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Viewpoint position="0 0 5"/>
      <Group><Shape><Box size="3 3 3"/></Shape><GeoTouchSensor DEF="T"><GeoOrigin
        containerField="geoOrigin" geoCoords="0 0 0"/></GeoTouchSensor></Group>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(64, 64)) as context:
        context.OnDraw(force=1)
        synthetic.dispatch(context, {'type': 'mousemove', 'buttons': [], 'x': 32, 'y': 32,
                                     'pick': True})
        for _ in range(3):
            context.OnDraw(force=1)
    touch = scene.getDEF('T')
    expected = geospatial.geo_coordinates(touch, touch.hitPoint_changed)[0]
    assert tuple(touch.hitGeoCoord_changed) == pytest.approx(tuple(expected))
    assert tuple(touch.hitPoint_changed)[2] == pytest.approx(1.5, abs=0.05)
