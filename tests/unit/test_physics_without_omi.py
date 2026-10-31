"""The engine runs on Jolt with omi_physics absent.

``pip install OpenGLContext`` brings pyjoltphysics and leaves omi_physics to the
``omi`` extra, so each check runs in a child interpreter where importing
``omi_physics`` raises ``ModuleNotFoundError``, as it does where the extra is
not installed. The engine's own modules come from this checkout.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip('pyjoltphysics')

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


def test_naming_omi_without_omi_physics_says_which_extra_to_install() -> None:
    out = run_without_omi('''
        from OpenGLContext.physics import Physics, PhysicsDefinition
        from OpenGLContext.physics.engine import EngineUnavailable
        try:
            Physics(PhysicsDefinition(engine='omi', mode='inline'))
        except EngineUnavailable as error:
            print('unavailable:', error)
    ''')
    assert out.startswith('unavailable:')
    assert 'OpenGLContext[omi]' in out


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
    'OpenGLContext.physics.omigltf',
    'OpenGLContext.physics.landscape',
    'OpenGLContext.physics.road',
    'OpenGLContext.physics.heightfield',
    'OpenGLContext.scenegraph.x3drigidbody',
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


def test_the_features_built_on_an_omi_world_name_the_extra() -> None:
    out = run_without_omi('''
        import logging
        from OpenGLContext.physics.engine import EngineUnavailable
        from OpenGLContext.physics.props import PropColliders
        from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
        from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
        from OpenGLContext.move.physicswalk import PhysicsWalkMixin
        from OpenGLContext.scenegraph import basenodes
        from OpenGLContext.scenegraph.x3drigidbody import RigidBodyCollection

        for make in (lambda: PropColliders(None, []), lambda: TerrainColliders(None),
                     lambda: PhysicsViewPlatform(None)):
            try:
                make()
            except EngineUnavailable as error:
                print('OpenGLContext[omi]' in str(error))

        class Host(PhysicsWalkMixin):
            sg = basenodes.sceneGraph(children=[basenodes.Shape(geometry=basenodes.Box())])

        heard = []
        handler = logging.Handler()
        handler.emit = lambda record: heard.append(record.getMessage())
        logging.getLogger().addHandler(handler)
        print(Host().ensurePhysicsWorld())
        collection = RigidBodyCollection()
        print(collection.step(), collection.step())
        print(sum('OpenGLContext[omi]' in message for message in heard))
    ''')
    assert out.split() == ['True', 'True', 'True', 'False', 'False', 'False', '2']


@pytest.mark.engines('jolt')
def test_an_engine_without_stand_ins_keeps_no_copy_of_the_bodies(physics_engine: str) -> None:
    from OpenGLContext.physics import Physics, PhysicsDefinition, Proxy

    physics = Physics(PhysicsDefinition(mode='inline'))
    try:
        with pytest.raises(NotImplementedError, match='no copy'):
            physics._engine.build_replica({}, None)
        with pytest.raises(NotImplementedError, match='no copy'):
            physics._engine.proxy_bounds(Proxy.sphere(1.0), (0, 0, 0), (0, 0, 0, 1))
        assert physics._engine.push_reach == 0.0
    finally:
        physics.close()
