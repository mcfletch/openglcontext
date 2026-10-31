"""The OMI glTF physics blocks of a document, read into the engine's own types."""
from __future__ import annotations

import math

import numpy as np
import pytest

from OpenGLContext.physics.omigltf import (BodyMotion, Collider, Gravity, JointAttach, MeshShape,
                                           Trigger, load_document)
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import Motion
from OpenGLContext.physics.types import CollisionFilter, Material


def document(**top: object) -> dict:
    return {'extensions': top, 'nodes': []}


def test_each_primitive_shape_is_a_proxy_of_its_kind_and_size() -> None:
    read = load_document(document(OMI_physics_shape={'shapes': [
        {'type': 'box', 'box': {'size': [2, 3, 4]}},
        {'type': 'sphere', 'sphere': {'radius': 0.25}},
        {'type': 'capsule', 'capsule': {'height': 1.5, 'radius': 0.3}},
        {'type': 'cylinder', 'cylinder': {'height': 2.0, 'radiusBottom': 0.5, 'radiusTop': 0.0}},
        {'type': 'box'},
    ]}))
    box, sphere, capsule, cone, unit = read.shapes
    assert all(isinstance(shape, Proxy) for shape in read.shapes)
    assert (box.kind, box.params['size']) == ('box', (2.0, 3.0, 4.0))
    assert (sphere.kind, sphere.params['radius']) == ('sphere', 0.25)
    assert capsule.params == {'height': 1.5, 'radius': 0.3}
    assert cone.params == {'height': 2.0, 'radius': 0.5, 'radius_top': 0.0}
    assert unit.params['size'] == (1.0, 1.0, 1.0)


def test_a_mesh_shape_names_its_mesh() -> None:
    read = load_document(document(OMI_physics_shape={'shapes': [
        {'type': 'convex', 'convex': {'mesh': 3}}, {'type': 'trimesh'}]}))
    assert read.shapes == [MeshShape('convex', 3), MeshShape('trimesh', -1)]


def test_an_unknown_shape_type_is_refused() -> None:
    with pytest.raises(ValueError, match='plane'):
        load_document(document(OMI_physics_shape={'shapes': [{'type': 'plane'}]}))


def test_materials_and_filters_are_the_engines_own() -> None:
    read = load_document(document(OMI_physics_body={
        'physicsMaterials': [{'staticFriction': 0.9, 'dynamicFriction': 0.7, 'restitution': 0.4,
                              'frictionCombine': 'minimum'}, {}],
        'collisionFilters': [{'collisionSystems': ['a'], 'collideWithSystems': ['b']},
                             {'notCollideWithSystems': ['c']}]}))
    assert read.materials == [Material(0.9, 0.7, 0.4, 'minimum', 'average'), Material()]
    assert isinstance(read.materials[0], Material)
    assert read.filters == [CollisionFilter(('a',), ('b',), ()), CollisionFilter((), None, ('c',))]


def test_a_nodes_blocks_are_read_under_its_index() -> None:
    read = load_document({'nodes': [
        {},
        {'extensions': {'OMI_physics_body': {
            'motion': {'type': 'dynamic', 'mass': 2.5, 'gravityFactor': 0.5,
                       'linearVelocity': [1, 0, 0]},
            'collider': {'shape': 1, 'physicsMaterial': 0},
            'joint': {'joint': 0, 'connectedNode': 3, 'enableCollision': True}}}},
        {'extensions': {'OMI_physics_body': {'trigger': {'shape': 0}},
                        'OMI_physics_gravity': {'type': 'point', 'gravity': 3.0, 'priority': 2}}},
    ]})
    assert set(read.node_bodies) == {1, 2}
    ball = read.node_bodies[1]
    assert ball.motion == BodyMotion('dynamic', 2.5, linearVelocity=(1.0, 0.0, 0.0), gravityFactor=0.5)
    assert ball.collider == Collider(1, 0, -1)
    assert ball.joint == JointAttach(0, 3, True)
    zone = read.node_bodies[2]
    assert zone.trigger == Trigger(0, -1)
    assert zone.gravity == Gravity('point', 3.0, priority=2)


@pytest.mark.parametrize(('given', 'kind'), [('dynamic', 'dynamic'), ('kinematic', 'kinematic'),
                                             ('static', 'static'), ('other', 'static')])
def test_a_motion_says_the_kind_of_body_it_makes(given: str, kind: str) -> None:
    made, motion = BodyMotion(given, mass=4.0, gravityFactor=0.25).body()
    assert made == kind
    assert motion == Motion(4.0, 0.0, 0.0, 0.25)


def test_document_gravity_and_joints() -> None:
    read = load_document(document(
        OMI_physics_gravity={'gravity': 1.62, 'direction': [0, 0, -1]},
        OMI_physics_joint={'physicsJoints': [{
            'limits': [{'angularAxes': [0], 'min': -0.5, 'max': 0.5}],
            'drives': [{'type': 'angular', 'velocityTarget': 2.0, 'maxForce': 10}]}]}))
    assert read.global_gravity == Gravity(gravity=1.62, direction=(0.0, 0.0, -1.0))
    (joint,) = read.joints
    (limit,) = joint.limits
    assert (limit.angularAxes, limit.min, limit.max, limit.stiffness) == ((0,), -0.5, 0.5, math.inf)
    (drive,) = joint.drives
    assert (drive.type, drive.velocityTarget, drive.maxForce, drive.positionTarget) == (
        'angular', 2.0, 10.0, None)


def test_an_empty_document_has_nothing() -> None:
    read = load_document({})
    assert (read.shapes, read.materials, read.filters, read.joints, read.node_bodies,
            read.global_gravity) == ([], [], [], [], {}, None)
    assert np.isfinite(BodyMotion().mass)
