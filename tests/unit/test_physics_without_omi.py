"""The engine runs on Jolt with omi_physics absent.

``pip install OpenGLContext`` brings pyjoltphysics and no omi_physics, while the
development environment installs omi_physics for one reference test, so each
check runs in a child interpreter where importing ``omi_physics`` raises
``ModuleNotFoundError``. The engine's own modules come from this checkout.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


CHECKOUT = Path(__file__).resolve().parents[2]

#: Prepended to every child script: omi_physics, and every module under it, cannot be imported.
BLOCK = textwrap.dedent('''
    import importlib.abc, sys

    class _NoOmi(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == 'omi_physics' or name.startswith('omi_physics.'):
                raise ModuleNotFoundError('No module named %r' % name, name=name)
            return None

    sys.meta_path.insert(0, _NoOmi())
    for _name in [n for n in sys.modules if n == 'omi_physics' or n.startswith('omi_physics.')]:
        del sys.modules[_name]
''')


def run_without_omi(script: str, timeout: float = 120.0) -> str:
    """Run ``script`` in a child interpreter that cannot import omi_physics; its stdout."""
    environment = dict(os.environ)
    environment.pop('OPENGLCONTEXT_PHYSICS_ENGINE', None)
    environment['PYTHONPATH'] = os.pathsep.join(
        [str(CHECKOUT)] + [p for p in environment.get('PYTHONPATH', '').split(os.pathsep) if p])
    done = subprocess.run(
        [sys.executable, '-c', BLOCK + textwrap.dedent(script)],
        capture_output=True, text=True, timeout=timeout, env=environment, cwd=str(CHECKOUT))
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def test_the_default_engine_is_jolt() -> None:
    out = run_without_omi('''
        from OpenGLContext.physics import PhysicsDefinition
        print(PhysicsDefinition().engine)
    ''')
    assert out.split() == ['jolt']


def test_naming_omi_says_the_engine_is_jolt_and_where_the_note_is() -> None:
    out = run_without_omi('''
        from OpenGLContext.physics import Physics, PhysicsDefinition
        try:
            Physics(PhysicsDefinition(engine='omi', mode='inline'))
        except ValueError as error:
            print('refused:', error)
    ''')
    assert out.startswith('refused:')
    assert "the engine is 'jolt'" in out
    assert 'Programs that named the omi engine' in out


def test_a_world_steps_bodies_and_characters() -> None:
    out = run_without_omi('''
        from OpenGLContext.physics import Physics, PhysicsDefinition, Proxy
        physics = Physics(PhysicsDefinition(mode='inline'))
        physics.enable(True)
        physics.add_static(None, Proxy.box((20.0, 1.0, 20.0)), translation=(0.0, -0.5, 0.0))
        crate = physics.add_dynamic(None, Proxy.box((0.5, 0.5, 0.5)), translation=(3.0, 2.0, 0.0))
        walker = physics.add_character(position=(0.0, 0.0, 0.0))
        walker.set_move((0.0, 0.0, -1.0))
        for _ in range(120):
            physics.frame(1.0 / 60.0)
        hit = physics.raycast((3.0, 5.0, 0.0), (0.0, -1.0, 0.0), 10.0)
        print(physics.engine.name)
        print(round(float(crate.position[1]), 2))
        print(walker.position[2] < -1.0)
        print(hit is not None and hit.body is crate)
        physics.close()
    ''')
    name, height, walked, struck = out.split()
    assert name == 'jolt'
    assert abs(float(height) - 0.25) < 0.02
    assert walked == 'True'
    assert struck == 'True'


#: Modules a program on the default engine imports, none of which may need omi_physics.
ENGINE_MODULES = (
    'OpenGLContext.physics.service',
    'OpenGLContext.physics.character',
    'OpenGLContext.physics.colliders',
    'OpenGLContext.physics.gltf_world',
    'OpenGLContext.physics.props',
    'OpenGLContext.physics.cooking',
    'OpenGLContext.physics.debugdraw',
    'OpenGLContext.physics.omigltf',
    'OpenGLContext.physics.landscape',
    'OpenGLContext.physics.road',
    'OpenGLContext.physics.heightfield',
    'OpenGLContext.scenegraph.x3drigidbody',
    'OpenGLContext.physics.x3drigid',
    'OpenGLContext.physics.x3djolt',
    'OpenGLContext.physics.massprops',
    'OpenGLContext.scenegraph.basenodes',
    'OpenGLContext.move.physicswalk',
    'OpenGLContext.move.physicsplatform',
    'OpenGLContext.move.terrainwalk',
    'OpenGLContext.move.thirdperson',
    'OpenGLContext.passes.zonelayers',
    'OpenGLContext.loaders.gltf.scene',
    'OpenGLContext.loaders.tiles3d.physics_colliders',
    'OpenGLContext.bin.physics_cook',
    'OpenGLContext.bin.terrain_view',
    'OpenGLContext.testing.physics',
)


def test_engine_modules_import_without_omi_physics() -> None:
    out = run_without_omi('''
        import importlib
        for name in %r:
            try:
                importlib.import_module(name)
            except ImportError as error:
                print(name, error)
        print('done')
    ''' % (ENGINE_MODULES,), timeout=240.0)
    assert out.split('\n')[0] == 'done', out


def test_walking_needs_no_omi_physics() -> None:
    out = run_without_omi('''
        import numpy as np
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.move.physicswalk import PhysicsWalkMixin
        from OpenGLContext.physics import Physics, PhysicsDefinition
        from OpenGLContext.scenegraph import basenodes

        class Platform:
            position = np.array([0.0, 1.6, 0.0, 1.0])
            def setPosition(self, position):
                self.position = np.array(tuple(position) + (1.0,))
            def setOrientation(self, orientation):
                pass

        class Host(PhysicsWalkMixin):
            movementManager = None
            sg = basenodes.sceneGraph(children=[basenodes.Shape(
                geometry=basenodes.Box(size=(20.0, 1.0, 20.0)))])
            def __init__(self):
                self.physics = Physics(PhysicsDefinition(mode='inline'))
                self.platform = Platform()
                self.contextDefinition = ContextDefinition()
            def triggerRedraw(self, force=0):
                pass
            def getNavigation(self):
                return None
            def updateNavigation(self, dt):
                pass

        host = Host()
        print(host.enablePhysics(True))
        for _ in range(20):
            host.stepPhysics(0.05)
        print(host.physicsPlatform.managed.grounded,
              round(float(host.physicsPlatform.managed.position[1]), 1))
        host.physics.close()
    ''')
    assert out.split() == ['True', 'True', '0.5']


def test_an_x3d_rigid_body_scene_steps_and_senses() -> None:
    out = run_without_omi('''
        from OpenGLContext.loaders.loader import Loader
        graph = Loader.loads(b"""<X3D version="4.0"><Scene>
          <CollidableShape DEF="BALL"><Shape containerField="shape"><Sphere radius="0.1"/></Shape>
          </CollidableShape>
          <CollidableShape DEF="GROUND" translation="0 -0.5 0">
            <Shape containerField="shape"><Box size="20 0.1 20"/></Shape></CollidableShape>
          <RigidBodyCollection DEF="C">
            <CollisionCollection containerField="collider">
              <CollidableShape USE="BALL"/><CollidableShape USE="GROUND"/></CollisionCollection>
            <RigidBody DEF="B" containerField="bodies" position="0 1 0">
              <CollidableShape USE="BALL" containerField="geometry"/></RigidBody>
          </RigidBodyCollection>
          <CollisionSensor DEF="S"><CollisionCollection containerField="collider">
            <CollidableShape USE="BALL"/><CollidableShape USE="GROUND"/></CollisionCollection>
          </CollisionSensor></Scene></X3D>""", 'rigid.x3d')
        collection, sensor = graph.getDEF('C'), graph.getDEF('S')
        for _ in range(120):
            collection.advance(1.0 / 60.0)
        sensor.sense()
        print(type(collection.system).__name__)
        print(round(float(graph.getDEF('B').position[1]), 2))
        print(sensor.isActive)
    ''')
    name, height, touching = out.split()
    assert name == 'JoltRigidSystem'
    assert abs(float(height) + 0.35) < 0.02
    assert touching == 'True'
