"""``oglc-x3d-rigidbody``: the X3D rigid body scene, with no window."""
import os

import numpy as np
import pytest
from vrml import node as vrml_node
from vrml import protofunctions

from OpenGLContext.bin import x3d_rigidbody
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.scenes import drawn_image, scene_context

FRAME = 1.0 / 60.0
COMPONENT = {'RigidBodyCollection', 'RigidBody', 'CollidableShape', 'CollidableOffset',
             'CollisionCollection', 'CollisionSpace', 'CollisionSensor', 'BallJoint',
             'DoubleAxisHingeJoint', 'MotorJoint', 'SingleAxisHingeJoint', 'SliderJoint',
             'UniversalJoint'}


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_rigidbody.RigidBodyScene(str(tmp_path_factory.mktemp('rigidbody')))
    assert background.wait_for_idle(20.0)
    return found


def _kinds(root):
    seen, kinds, todo = set(), set(), [root]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        kinds.add(getattr(type(current), 'PROTO', type(current).__name__))
        for declared in protofunctions.getFields(current):
            value = getattr(current, declared.name, None)
            if isinstance(declared, vrml_node.SFNode) and value:
                todo.append(value)
            elif isinstance(declared, vrml_node.MFNode):
                todo.extend(child for child in value or () if child)
    return kinds


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_maps_it_names_are_written_beside_it(demo):
    assert {'x3d_rigidbody.x3d', 'marble_base.png', 'brick_normal.png',
            'sandstone_mr.png'} <= set(os.listdir(demo.directory))


def test_it_uses_every_rigid_body_node(demo):
    assert COMPONENT <= _kinds(demo.scene)


def test_the_workshop_runs(demo):
    demo.press('r')
    scene = demo.scene
    angles = []
    sensor = scene.getDEF('BOUNCE-SENSOR')
    for _ in range(round(4.0 / FRAME)):
        sensor.sense()
        demo.workshop.advance(FRAME)
        angles.append(float(scene.getDEF('DOOR-HINGE').angle))
    assert 0.25 < scene.getDEF('CRATE-BODY-1').position[1] < 0.35
    assert max(angles) == pytest.approx(1.6, abs=0.1)
    assert min(angles[60:]) > -0.2
    assert scene.getDEF('WHEEL-HINGE').hinge2AngleRate == pytest.approx(3.0, abs=0.1)
    assert scene.getDEF('PISTON-SLIDE').separation == pytest.approx(1.0, abs=0.05)
    assert abs(scene.getDEF('SHAFT-BODY-2').angularVelocity).max() > 0.1
    assert scene.getDEF('DUMBBELL').position[1] == pytest.approx(0.15, abs=0.05)


def test_the_ball_bounces_on_the_sensors_contacts(demo):
    demo.press('r')
    ball = demo.scene.getDEF('BALL-BODY')
    heights = []
    sensor = demo.scene.getDEF('BOUNCE-SENSOR')
    for _ in range(round(3.0 / FRAME)):
        sensor.sense()
        demo.workshop.advance(FRAME)
        heights.append(float(ball.position[1]))
    landed = int(np.argmin(heights[:90]))
    assert max(heights[landed:]) > 1.5


def test_the_keys(demo):
    demo.press('r')
    assert demo.press('p') == 'paused'
    before = np.array(demo.scene.getDEF('BALL-BODY').position)
    demo.workshop.advance(0.5)
    assert np.allclose(demo.scene.getDEF('BALL-BODY').position, before)
    assert demo.press('p') == 'running'
    assert demo.press('r') == 'started again'
    assert demo.press('x') == ''


def test_it_draws(gl_context, demo):
    demo.press('r')
    with scene_context(demo.scene, size=(160, 90)) as context:
        for _ in range(3):
            context.renderQueue.run()
            context.OnDraw(force=1)
        image = drawn_image(context).astype(int)
    warm = (image[:, :, 0] > image[:, :, 2] + 40)
    assert warm.mean() > 0.05
