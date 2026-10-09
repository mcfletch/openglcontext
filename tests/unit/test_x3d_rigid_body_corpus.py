"""Web3D's RigidBodyPhysics examples (Basic archive), loaded and simulated.

Skipped where the example archives have not been fetched
(`vrml.x3d.corpus.fetch`). Each document's collections and sensors are
stepped by hand, a frame at a time, as the render loop steps them.
"""
import logging
import os

import numpy as np
import pytest
from vrml import node as vrml_node
from vrml import protofunctions
from vrml.x3d import corpus
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.x3drigidbody import CollisionSensor, RigidBodyCollection

FRAME = 1.0 / 60.0
FOLDER = os.path.join(corpus.examples('Basic'), 'RigidBodyPhysics')

pytestmark = pytest.mark.skipif(not os.path.isdir(FOLDER),
                                reason='the Basic example archive has not been fetched')


def nodes_of(root):
    """Every node reachable from `root`, each once"""
    found, seen, todo = [], set(), [root]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        for declared in protofunctions.getFields(current):
            if isinstance(declared, vrml_node.SFNode):
                value = getattr(current, declared.name, None)
                if value:
                    todo.append(value)
            elif isinstance(declared, vrml_node.MFNode):
                todo.extend(child for child in getattr(current, declared.name, ()) or ()
                            if child)
    return found


def simulate(name, seconds, watch=None):
    """Load `name` and step it for `seconds`; its scene, and `watch(scene)` each frame"""
    path = os.path.join(FOLDER, name)
    logging.disable(logging.ERROR)
    try:
        with open(path, 'rb') as stream:
            scene = Loader.loads(stream.read(), path)
    finally:
        logging.disable(logging.NOTSET)
    found = nodes_of(scene)
    collections = [each for each in found if isinstance(each, RigidBodyCollection)]
    sensors = [each for each in found if isinstance(each, CollisionSensor)]
    assert collections
    seen = []
    for _ in range(round(seconds / FRAME)):
        for sensor in sensors:
            sensor.sense()
        for collection in collections:
            collection.advance(FRAME)
        if watch is not None:
            seen.append(watch(scene))
    return scene, seen


def test_the_ball_bounces_on_the_ground():
    _, heights = simulate('BallBounceSimple.x3d', 4.0,
                          lambda scene: float(scene.getDEF('BODY-1').position[1]))
    landed = int(np.argmin(heights))
    assert heights[landed] > -0.45
    assert max(heights[landed:]) > 1.5


@pytest.mark.parametrize('name', ['BallBounce.x3d', 'BounceTrimesh.x3d'])
def test_contacts_a_script_would_correct_never_arrive(name):
    """The routed contacts pass through a Script, which is not run, so the ball falls"""
    scene, _ = simulate(name, 2.0)
    assert scene.getDEF('BODY-1').position[1] < -10.0


def test_two_bodies_with_nothing_to_meet_fall():
    scene, _ = simulate('BodyGeometry.x3d', 1.0)
    for name in ('BODY-1', 'BODY-2'):
        assert scene.getDEF(name).position[1] == pytest.approx(-4.9, abs=0.1)


@pytest.mark.parametrize('name', ['SliderJointExample.x3d', 'DoubleHingeJoint.x3d',
                                  'MotorJoint.x3d'])
def test_the_slider_carries_its_body_along_its_axis(name):
    scene, _ = simulate(name, 3.0)
    moved = np.asarray(scene.getDEF('BODY-2').position) - (0.3, 0.0, 0.0)
    assert moved[0] == pytest.approx(0.3, abs=0.02)
    assert np.allclose(moved[1:], 0.0, atol=0.01)
    assert np.allclose(scene.getDEF('BODY-1').position, (-0.3, 0.0, 0.0), atol=0.01)


@pytest.mark.parametrize('name, anchors', [
    ('SingleHingeJoint.x3d', ((-0.15, 0.0, 0.0), (0.15, 0.0, 0.0))),
    ('BallJointExample.x3d', ((0.15, 0.0, 0.0), (0.4, 0.0, 0.1))),
])
def test_the_chain_swings_and_holds_together(name, anchors):
    scene, _ = simulate(name, 2.0)
    collection = next(each for each in nodes_of(scene) if isinstance(each, RigidBodyCollection))
    world = collection.system.world
    built = sorted(collection.system.joints, key=lambda found: float(found.node.anchorPoint[0]))
    assert [tuple(found.node.anchorPoint) for found in built] == [
        pytest.approx(anchor) for anchor in anchors]
    for found in built:
        assert np.linalg.norm(found.joint.anchor_a(world) - found.joint.anchor_b(world)) < 0.02
    assert scene.getDEF('BODY-3').position[1] < -0.1


def test_the_universal_joint_turns_the_second_bar():
    scene, _ = simulate('UniversalJointExample.x3d', 2.0)
    assert np.linalg.norm(scene.getDEF('BODY-2').angularVelocity) > 0.01
    collection = next(each for each in nodes_of(scene) if isinstance(each, RigidBodyCollection))
    world = collection.system.world
    joint = collection.system.joints[0].joint
    assert abs(float(np.dot(joint.axis1(world), joint.axis2(world)))) < 0.01
    assert np.linalg.norm(joint.anchor_a(world) - joint.anchor_b(world)) < 0.01


def test_the_car_waits_for_the_script_that_enables_it():
    scene, _ = simulate('CarDemoMain.x3d', 1.0)
    assert np.allclose(scene.getDEF('CAR-BODY').position, (0.0, 1.25, 0.0))
