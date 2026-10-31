"""The engine's Cloth and Ragdoll nodes in X3D documents, and a Cloth simulated where it is drawn."""
import math

import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.softnodes import Cloth, Ragdoll, rotation_quaternion

WORLD = b'''#X3D V4.0 utf8
PROFILE Immersive
DEF flag Cloth {
  translation 0 2 0
  mass 0.3 pinned [ 0 4 ] wind 0 0 1.5 linearDamping 1
  children [ Shape {
    appearance Appearance { material PhysicalMaterial { baseColor 0.6 0.1 0.1 } }
    geometry IndexedTriangleSet {
      index [ 0 5 1  1 5 6  1 6 2  2 6 7  2 7 3  3 7 8  3 8 4  4 8 9 ]
      coord Coordinate { point [ 0 0 0, 0.25 0 0, 0.5 0 0, 0.75 0 0, 1 0 0,
                                 0 0 0.5, 0.25 0 0.5, 0.5 0 0.5, 0.75 0 0.5, 1 0 0.5 ] }
    }
  } ]
}
DEF doll Ragdoll { url "figure.glb" mode "POWERED" blend 0.5 mass 80 rootForce 4000 }
'''


def test_a_document_names_both_nodes():
    scene = Loader.loads(WORLD, 'cloth.x3dv')
    assert [str(p) for p in scene.problems if p.severity != 'info'] == []
    flag = scene.getDEF('flag')
    assert type(flag) is Cloth and list(flag.pinned) == [0, 4]
    assert tuple(flag.wind) == pytest.approx((0.0, 0.0, 1.5))
    doll = scene.getDEF('doll')
    assert type(doll) is Ragdoll and doll.mode == 'POWERED' and doll.mass == 80.0


def test_both_are_written_in_their_component_and_read_back():
    from vrml import x3d as documents
    scene = Loader.loads(WORLD, 'cloth.x3dv')
    for encoding in ('classic', 'xml', 'json'):
        text = documents.dumps(scene, encoding=encoding)
        assert 'OpenGLContext' in text and 'Cloth' in text and 'Ragdoll' in text
        name = 'again.' + {'classic': 'x3dv', 'xml': 'x3d', 'json': 'x3dj'}[encoding]
        again = Loader.loads(text.encode('utf-8'), name)
        assert [str(p) for p in again.problems if p.severity != 'info'] == []
        flag = again.getDEF('flag')
        assert type(flag) is Cloth and list(flag.pinned) == [0, 4]
        assert flag.mass == pytest.approx(0.3)
        doll = again.getDEF('doll')
        assert list(doll.url) == ['figure.glb'] and doll.rootForce == 4000.0


def test_the_classic_text_names_the_component():
    from vrml import x3d as documents
    text = documents.dumps(Loader.loads(WORLD, 'cloth.x3dv'), encoding='classic')
    assert 'COMPONENT OpenGLContext:1' in text


def test_an_sfrotation_is_a_quaternion():
    assert rotation_quaternion((0, 1, 0, math.pi)) == pytest.approx((0.0, 1.0, 0.0, 0.0), abs=1e-12)
    assert rotation_quaternion((0, 0, 0, 1.0)) == (0.0, 0.0, 0.0, 1.0)


class _Queue:
    def __init__(self):
        self.calls = []

    def call(self, function, *arguments):
        self.calls.append((function, arguments))


class _Context:
    """What the nodes ask of a context: its physics and its render queue."""

    def __init__(self, physics):
        self.physics = physics
        self.renderQueue = _Queue()
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


def test_a_bound_cloth_hangs_from_its_pins_and_is_let_go_when_unbound():
    from OpenGLContext.physics import Physics, PhysicsDefinition
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=60.0))
    try:
        scene = Loader.loads(WORLD, 'cloth.x3dv')
        flag = scene.getDEF('flag')
        context = _Context(physics)
        assert flag.bind(context) and flag.bind(context)
        assert len(context.renderQueue.calls) == 1
        soft = flag.soft_mesh(context)
        mesh = flag.children[0].geometry
        assert soft.mesh is mesh
        for _ in range(120):
            flag.tick(context)
            physics.frame(1 / 60)
        world = mesh.positions.astype('d') + mesh.origin
        assert world[0] == pytest.approx((0.0, 2.0, 0.0), abs=2e-3)
        assert world[4] == pytest.approx((1.0, 2.0, 0.0), abs=2e-3)
        assert world[:, 1].min() < 1.8
        # The wind blows along +z.
        assert world[5:, 2].min() > 0.05     # the wind along +z holds the free edge out
        flag.unbindContext(context)
        assert flag.soft_mesh(context) is None and not soft.soft.alive
        assert flag.tick(context) is None
    finally:
        physics.close()


def test_a_cloth_with_no_shape_says_so(caplog):
    from OpenGLContext.physics import Physics, PhysicsDefinition
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt'))
    try:
        context = _Context(physics)
        Cloth().bind(context)
        assert 'not simulated' in caplog.text
        Cloth(enabled=False).bind(context)
    finally:
        physics.close()


def test_a_bound_ragdoll_draws_its_character_and_changes_mode(monkeypatch):
    from OpenGLContext.character import model as model_module
    from OpenGLContext.physics import Physics, PhysicsDefinition
    from ._ragdoll_assets import BONES, figure

    class Model:
        def __init__(self):
            self.mixer = figure()
            self.humanoid = type('H', (), {'bones': BONES})()
            from OpenGLContext.scenegraph.basenodes import Transform
            self.group = Transform()
            self.clips = {}

        def play(self, name):
            raise AssertionError('no clips to play')

    monkeypatch.setattr(model_module.CharacterModel, 'load', classmethod(lambda cls, url: Model()))
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=120.0))
    try:
        doll = Ragdoll(url=['figure.glb'], mode='KINEMATIC', translation=(1.0, 0.0, 0.0))
        context = _Context(physics)
        doll.bind(context)
        assert doll.renderedChildren()[0] is doll.__dict__['_model'].group
        figure_ = doll.figure(context)
        for _ in range(5):
            doll.tick(context)
            physics.frame(1 / 60)
        hips = figure_.ragdoll.bone('hips').position
        assert hips == pytest.approx((1.0, 0.95, 0.0), abs=1e-3)
        doll.mode = 'LIMP'
        doll.tick(context)
        assert figure_.ragdoll.mode.value == 'limp' and not figure_.following
        doll.unbindContext(context)
        assert not figure_.ragdoll.alive
    finally:
        physics.close()


def _cloth_mesh():
    from OpenGLContext.physics.softbodies import SoftBodySpec
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    grid = SoftBodySpec.cloth(1.0, 1.0, 5, 5)
    return PBRMesh(positions=grid.positions.astype('f'),
                   normals=np.tile(np.array([0, 1, 0], 'f'), (25, 1)),
                   indices=grid.faces.ravel())


def test_a_gltf_node_tagged_cloth_loads_as_a_cloth():
    from OpenGLContext.loaders import gltf
    from OpenGLContext.loaders.gltf import hooks
    from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
    assert hooks.registered('cloth') is not None
    root = SceneNode(name='flag', mesh=_cloth_mesh(), translation=(0.0, 2.0, 0.0), extras={
        'OGLC_hook': {'kind': 'cloth', 'mass': 0.4, 'pinned': [0, 4, -1, 'x'],
                      'wind': [0, 0, 2], 'compliance': -3}})
    scene = gltf.load_gltf(write_glb(root))
    found = []
    stack = [scene.group]
    while stack:
        item = stack.pop()
        if isinstance(item, Cloth):
            found.append(item)
        stack.extend(getattr(item, 'children', None) or [])
    assert len(found) == 1
    cloth = found[0]
    assert cloth.mass == pytest.approx(0.4) and list(cloth.pinned) == [0, 4]
    assert tuple(cloth.wind) == pytest.approx((0.0, 0.0, 2.0))
    assert cloth.compliance == 0.0          # held to its bound, and reported
    assert tuple(cloth.translation) == pytest.approx((0.0, 2.0, 0.0))
    assert cloth._shape() is not None


def test_a_material_tagged_cloth_is_not_read():
    from OpenGLContext.scenegraph.softnodes import cloth_hook
    assert cloth_hook(type('C', (), {'at': 'material'})()) is None


TURNED = WORLD.replace(b'translation 0 2 0', b'translation 0 2 0 rotation 0 0 1 1.5707963')


def test_a_cloth_bound_again_starts_where_it_was_authored():
    """Vertex 4, authored at (1, 0, 0), is turned a quarter about z and lifted 2 m: (0, 3, 0)"""
    from OpenGLContext.physics import Physics, PhysicsDefinition
    flag = Loader.loads(TURNED, 'cloth.x3dv').getDEF('flag')
    for _ in range(2):
        physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=60.0))
        try:
            context = _Context(physics)
            flag.bind(context)
            mesh = flag.children[0].geometry
            world = mesh.positions.astype('d') + mesh.origin
            assert world[4] == pytest.approx((0.0, 3.0, 0.0), abs=1e-5)
            assert world[0] == pytest.approx((0.0, 2.0, 0.0), abs=1e-5)
            for _ in range(60):
                flag.tick(context)
                physics.frame(1 / 60)
            world = mesh.positions.astype('d') + mesh.origin
            assert world[4] == pytest.approx((0.0, 3.0, 0.0), abs=2e-3)
            flag.unbindContext(context)
        finally:
            physics.close()


def _drawn_matrix(chain):
    """The row-vector matrix a renderer draws the last node of ``chain`` (outermost first) with"""
    from vrml.vrml97 import nodepath
    path = nodepath.NodePath([])
    for item in chain:
        path = path + item
    return np.asarray(path.transformMatrix(), dtype='d')


def test_a_gltf_cloth_under_a_moved_parent_is_simulated_where_it_is_drawn():
    """The flag at (0, 2, 0) in a cart at (5, 0, 0) turned a quarter about z stands at (3, 0, 0)"""
    from OpenGLContext.loaders import gltf
    from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
    from OpenGLContext.physics import Physics, PhysicsDefinition
    flag = SceneNode(name='flag', mesh=_cloth_mesh(), translation=(0.0, 2.0, 0.0),
                     extras={'OGLC_hook': {'kind': 'cloth', 'pinned': [0, 4]}})
    cart = SceneNode(name='cart', translation=(5.0, 0.0, 0.0),
                     rotation=(0.0, 0.0, 0.7071068, 0.7071068), children=[flag])
    scene = gltf.load_gltf(write_glb(cart))
    found = []
    stack = [(scene.group, [])]
    while stack:
        item, chain = stack.pop()
        if isinstance(item, Cloth):
            found.append((item, chain))
            continue
        stack.extend((child, [*chain, item]) for child in getattr(item, 'children', None) or [])
    (cloth, chain), = found
    assert tuple(cloth.translation) == pytest.approx((3.0, 0.0, 0.0), abs=1e-5)
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=60.0))
    try:
        context = _Context(physics)
        cloth.bind(context)
        for _ in range(30):
            cloth.tick(context)
            physics.frame(1 / 60)
        soft = cloth.soft_mesh(context)
        mesh = soft.mesh
        simulated = soft.soft.frame().positions[soft.index] + soft.soft.frame().origin
        local = mesh.positions.astype('d') + mesh.origin
        drawn = np.column_stack([local, np.ones(len(local))]) @ _drawn_matrix([*chain, cloth])
        assert drawn[:, :3] == pytest.approx(simulated, abs=1e-4)
        # The pins hold the flag's top corners where the cart carries them.
        authored = np.asarray(_cloth_mesh().positions, dtype='d')
        for vertex in (0, 4):
            x, y, z = authored[vertex]
            assert drawn[vertex, :3] == pytest.approx((5.0 - (y + 2.0), x, z), abs=2e-3)
    finally:
        physics.close()
