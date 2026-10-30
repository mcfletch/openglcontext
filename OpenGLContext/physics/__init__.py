"""Rigid bodies, characters and joints for a context.

Every context has a physics service, ``context.physics``
(:class:`~OpenGLContext.physics.service.Physics`), made on first use. A game
adds bodies, characters and joints through it and reads them through the handles
it returns; the world steps itself. The names a game needs are importable from
this package::

    from OpenGLContext.physics import CharacterCapabilities, Material, Proxy

They are loaded on first use, so importing the package imports neither the
service nor the engine that steps the world. No name here is the engine's: the
service converts its own values to the engine's in
:mod:`~OpenGLContext.physics.omi_adapter`. The modules:

* :mod:`~OpenGLContext.physics.service` -- the service: adding, removing,
  queries, events, the frame.
* :mod:`~OpenGLContext.physics.body`, :mod:`~OpenGLContext.physics.character`
  and :mod:`~OpenGLContext.physics.joints` -- the handles it returns.
* :mod:`~OpenGLContext.physics.proxy` -- collision shapes, cooked from nodes.
* :mod:`~OpenGLContext.physics.types` -- materials, collision filters,
  characters' capabilities and state, poses, the world's counts and the
  engine's description.
* :mod:`~OpenGLContext.physics.worker` and :mod:`~OpenGLContext.physics.runtime`
  -- where and how the world is stepped.
* :mod:`~OpenGLContext.physics.debugdraw` -- an instanced wireframe overlay of the
  world's proxies, contacts and velocities.
* :mod:`~OpenGLContext.physics.gltf_world` -- a loaded glTF scenegraph as a
  collision world.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.joints import Joint
    from OpenGLContext.physics.proxy import Proxy
    from OpenGLContext.physics.service import Physics
    from OpenGLContext.physics.settings import PhysicsDefinition
    from OpenGLContext.physics.types import (
        CharacterCapabilities, CharacterState, CollisionFilter, EngineInfo, GravityZone, Material,
        Poses, WorldCounts,
    )

#: Each exported name and the module it is defined in.
_HOMES = {
    'Body': 'OpenGLContext.physics.body',
    'Character': 'OpenGLContext.physics.character',
    'CharacterCapabilities': 'OpenGLContext.physics.types',
    'CharacterState': 'OpenGLContext.physics.types',
    'CollisionFilter': 'OpenGLContext.physics.types',
    'EngineInfo': 'OpenGLContext.physics.types',
    'GravityZone': 'OpenGLContext.physics.types',
    'Joint': 'OpenGLContext.physics.joints',
    'Material': 'OpenGLContext.physics.types',
    'Physics': 'OpenGLContext.physics.service',
    'PhysicsDefinition': 'OpenGLContext.physics.settings',
    'Poses': 'OpenGLContext.physics.types',
    'Proxy': 'OpenGLContext.physics.proxy',
    'WorldCounts': 'OpenGLContext.physics.types',
}

__all__ = ['Body', 'Character', 'CharacterCapabilities', 'CharacterState', 'CollisionFilter',
           'EngineInfo', 'GravityZone', 'Joint', 'Material', 'Physics', 'PhysicsDefinition', 'Poses',
           'Proxy', 'WorldCounts']


def __getattr__(name: str) -> Any:
    home = _HOMES.get(name)
    if home is None:
        raise AttributeError('module %r has no attribute %r' % (__name__, name))
    value = getattr(importlib.import_module(home), name)
    globals()[name] = value
    return value
