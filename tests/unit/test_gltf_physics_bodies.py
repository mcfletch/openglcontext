"""A glTF document with OMI physics bodies needs no call to become a physics world.

The loader tags each node that carries an ``OMI_physics_body`` with the body it
describes; a physics service that sees the node in the scene makes the body.
"""
import base64
import json

import numpy as np
import pygltflib
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.scene import unread_required
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.testing import physics as physics_testing


def _b64(data: bytes) -> str:
    return 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')


def document(bodies=True):
    """A floor, a ball and a trigger volume, each a triangle mesh with a body block."""
    positions = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='<f4')
    blob = positions.tobytes()
    body = (lambda **block: {'OMI_physics_body': block}) if bodies else (lambda **block: {})
    document = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['OMI_physics_body', 'OMI_physics_shape'] if bodies else [],
        'extensionsRequired': ['OMI_physics_body'] if bodies else [],
        'buffers': [{'byteLength': len(blob), 'uri': _b64(blob)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': positions.nbytes}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                       'min': [0, 0, 0], 'max': [1, 1, 0]}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'nodes': [
            {'name': 'Floor', 'mesh': 0, 'translation': [0, -0.5, 0],
             'extensions': body(motion={'type': 'static'},
                                collider={'shape': 0, 'physicsMaterial': 0})},
            {'name': 'Ball', 'mesh': 0, 'translation': [0, 3, 0],
             'extensions': body(motion={'type': 'dynamic', 'mass': 2.0},
                                collider={'shape': 1, 'physicsMaterial': 1})},
            {'name': 'Zone', 'translation': [10, 1, 0],
             'extensions': body(trigger={'shape': 0})},
            {'name': 'Plain', 'mesh': 0, 'translation': [20, 0, 0]},
        ],
        'scenes': [{'nodes': [0, 1, 2, 3]}],
        'scene': 0,
    }
    if bodies:
        document['extensions'] = {
            'OMI_physics_shape': {'shapes': [
                {'type': 'box', 'box': {'size': [20, 1, 20]}},
                {'type': 'sphere', 'sphere': {'radius': 0.5}},
            ]},
            'OMI_physics_body': {'physicsMaterials': [
                {'staticFriction': 0.6, 'dynamicFriction': 0.6, 'restitution': 0.0},
                {'staticFriction': 0.5, 'dynamicFriction': 0.5, 'restitution': 0.0},
            ]},
        }
    return document


def load(tmp_path, **named):
    path = tmp_path / 'bodies.gltf'
    path.write_text(json.dumps(document(**named)))
    return gltf.load_gltf(str(path))


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('maxCatchUp', 2.0)
    named.setdefault('tickHz', 100.0)
    return Physics(PhysicsDefinition(**named))


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


def run_for(physics, seconds, frame=0.02):
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


def test_the_loader_keeps_the_physics_document_on_the_scene(tmp_path):
    scene = load(tmp_path)
    assert scene.physics is not None
    assert set(scene.physics.node_bodies) == {0, 1, 2}
    assert [shape.kind for shape in scene.physics.shapes] == ['box', 'sphere']


def test_a_document_without_bodies_has_no_physics(tmp_path):
    assert load(tmp_path, bodies=False).physics is None


def test_the_nodes_that_carry_a_body_are_tagged_with_it(tmp_path):
    scene = load(tmp_path)
    tagged = [index for index, transform in scene.node_transforms.items()
              if getattr(transform, 'omiPhysics', None) is not None]
    assert tagged == [0, 1, 2]


def test_the_extensions_are_no_longer_unread(tmp_path):
    load(tmp_path)
    assert unread_required(pygltflib.GLTF2.load(str(tmp_path / 'bodies.gltf'))) == []


def test_each_body_of_the_document_is_made_when_the_scene_is_seen(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    kinds = {name: getattr(physics.body_for(scene.node_transforms[index]), 'kind', None)
             for name, index in (('floor', 0), ('ball', 1), ('zone', 2), ('plain', 3))}
    assert kinds == {'floor': 'static', 'ball': 'dynamic', 'zone': 'trigger',
                     'plain': 'static'}


def test_the_ball_falls_on_the_floor_the_document_describes(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    physics.wait_cooked(20.0)
    run_for(physics, 2.0)
    ball = scene.node_transforms[1]
    assert ball.translation[1] == pytest.approx(0.5, abs=0.08)


def test_the_balls_mass_and_material_come_from_the_document(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    body = physics.body_for(scene.node_transforms[1])
    assert body.mass == pytest.approx(2.0)
    assert physics_testing.material(physics, body).staticFriction == pytest.approx(0.5)


def test_a_body_is_made_once_whatever_is_under_the_tagged_node(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    physics.wait_cooked(20.0)
    assert len(physics._bodies) == 4          # floor, ball, zone and the plain mesh


def test_bodies_leave_the_world_with_their_nodes(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    ball = physics.body_for(scene.node_transforms[1])
    scene.group.children = [child for child in scene.group.children
                            if child is not scene.node_transforms[1]]
    physics.scenery_changed(scene.group, 2)
    assert not ball.alive


def test_a_handler_on_the_ball_hears_it_land(tmp_path, physics):
    scene = load(tmp_path)
    physics.scenery_changed(scene.group, 1)
    heard = []
    keep = heard.append
    physics.body_for(scene.node_transforms[1]).addEventHandler('hit', function=keep)
    physics.wait_cooked(20.0)
    run_for(physics, 2.0)
    assert len(heard) == 1


@pytest.mark.parametrize('kind', ['trimesh', 'convex'])
def test_a_mesh_shape_is_made_from_the_triangles_its_node_draws(tmp_path, physics, kind):
    given = document()
    given['extensions']['OMI_physics_shape']['shapes'][0] = {'type': kind, kind: {'mesh': 0}}
    path = tmp_path / 'mesh.gltf'
    path.write_text(json.dumps(given))
    scene = gltf.load_gltf(str(path))
    physics.scenery_changed(scene.group, 1)
    floor = physics.body_for(scene.node_transforms[0])
    assert floor.proxy.kind == kind
    assert np.allclose(np.sort(floor.proxy.params['points'], axis=0),
                       np.sort([(0, 0, 0), (1, 0, 0), (0, 1, 0)], axis=0))
    # The zone's trigger names the same shape and draws nothing to make it from.
    assert physics.body_for(scene.node_transforms[2]) is None
