"""The environmental sensors, told each frame what they sense.

The behaviour is pyvrml97's (``vrml.x3d.sensors``); the pass tells each sensor
the viewer's pose (ProximitySensor), its target's pose (TransformSensor) or
whether its box is in view (VisibilitySensor), in the sensor's coordinates
(``OpenGLContext.scenegraph.x3dsensors``).
"""
import math

import numpy as np
import pytest
from vrml.vrml97 import transformmatrix
from vrml.x3d import sensors

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import x3dsensors


def placed(translation=(0, 0, 0), rotation=(0, 0, 1, 0)):
    """A row-vector local-to-world matrix"""
    found = transformmatrix.transformMatrix(translation=translation, rotation=rotation)
    return np.identity(4) if found is None else found


def test_a_pose_in_a_sensors_coordinates():
    position, rotation = x3dsensors.pose_in(placed((0, 0, 5)), placed((0, 0, 2)))
    assert position == pytest.approx((0, 0, 3))
    assert rotation[3] == pytest.approx(0.0, abs=1e-6)


def test_a_turned_viewer_is_turned_in_the_sensors_coordinates():
    viewer = placed((1, 0, 0), (0, 1, 0, math.pi / 2))
    position, rotation = x3dsensors.pose_in(viewer, placed())
    assert position == pytest.approx((1, 0, 0))
    assert np.allclose(rotation, (0, 1, 0, math.pi / 2), atol=1e-5)


def test_a_turned_sensor_turns_the_viewers_pose():
    sensor = placed((0, 0, 0), (0, 1, 0, math.pi / 2))
    position, rotation = x3dsensors.pose_in(placed((5, 0, 0)), sensor)
    assert position == pytest.approx((0, 0, 5), abs=1e-5)
    assert np.allclose(rotation, (0, 1, 0, -math.pi / 2), atol=1e-5) or \
        np.allclose(rotation, (0, -1, 0, math.pi / 2), atol=1e-5)


@pytest.mark.parametrize('name', ['ProximitySensor', 'TransformSensor', 'VisibilitySensor'])
def test_each_is_pyvrml97s(name):
    assert issubclass(prototypes()[name], sensors.SENSORS[name])


def document(body):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    return Loader.loads(b'<X3D version="4.0"><Scene>' + body + b'</Scene></X3D>', 'scene.x3d')


def drawn(scene, frames=2):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    with scene_context(scene) as context:
        for _ in range(frames):
            context.OnDraw(force=1)


def test_a_proximity_sensor_sees_the_viewer(gl_context):
    scene = document(b'''<Viewpoint position="0 1 3"/>
      <Transform translation="0 0 -2"><ProximitySensor DEF="P" size="20 20 20"/></Transform>
      <ProximitySensor DEF="FAR" center="100 0 0" size="1 1 1"/>''')
    drawn(scene)
    near = scene.getDEF('P')
    assert near.isActive is True
    assert tuple(near.position_changed) == pytest.approx((0, 1, 5))
    assert 'isActive' not in scene.getDEF('FAR').__dict__


def test_a_visibility_sensor_sees_what_is_in_front(gl_context):
    scene = document(b'''<Viewpoint position="0 0 10"/>
      <VisibilitySensor DEF="AHEAD" size="1 1 1"/>
      <VisibilitySensor DEF="BEHIND" center="0 0 30" size="1 1 1"/>''')
    drawn(scene)
    assert scene.getDEF('AHEAD').isActive is True
    assert 'isActive' not in scene.getDEF('BEHIND').__dict__


def test_a_transform_sensor_sees_its_target(gl_context):
    scene = document(b'''<Viewpoint position="0 0 10"/>
      <Transform DEF="T" translation="1 0 0"><Shape><Box/></Shape></Transform>
      <TransformSensor DEF="S" size="4 4 4"><Transform USE="T" containerField="targetObject"/>
      </TransformSensor>''')
    drawn(scene)
    sensor = scene.getDEF('S')
    assert sensor.targetObject is scene.getDEF('T')
    assert sensor.isActive is True
    assert tuple(sensor.position_changed) == pytest.approx((1, 0, 0))
    scene.getDEF('T').translation = (10, 0, 0)
    drawn(scene, frames=1)
    assert sensor.isActive is False


def test_a_proximity_sensors_route_moves_a_transform(gl_context):
    scene = document(b'''<Viewpoint position="0 0 3"/>
      <ProximitySensor DEF="P" size="20 20 20"/>
      <Transform DEF="FOLLOW"/>
      <ROUTE fromNode="P" fromField="position_changed" toNode="FOLLOW" toField="set_translation"/>''')
    drawn(scene)
    assert tuple(scene.getDEF('FOLLOW').translation) == pytest.approx((0, 0, 3))
