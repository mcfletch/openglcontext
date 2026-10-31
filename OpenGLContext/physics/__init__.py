"""Rigid bodies, characters and joints for a context.

Every context has a physics service, ``context.physics``
(:class:`~OpenGLContext.physics.service.Physics`), made on first use. A game
adds bodies, characters and joints through it and reads them through the handles
it returns; the world steps itself. The names a game needs are importable from
this package::

    from OpenGLContext.physics import CharacterCapabilities, Material, Proxy

They are loaded on first use, so importing the package imports neither the
service nor the engine that steps the world. No name here is an engine's: each
engine converts the service's values to its own (:mod:`~OpenGLContext.physics.joltengine`,
and the deprecated omi engine's :mod:`~OpenGLContext.physics.omi_adapter`). The modules:

* :mod:`~OpenGLContext.physics.service` -- the service: adding, removing,
  queries, events, the frame.
* :mod:`~OpenGLContext.physics.body`, :mod:`~OpenGLContext.physics.character`
  and :mod:`~OpenGLContext.physics.joints` -- the handles it returns.
* :mod:`~OpenGLContext.physics.proxy` and :mod:`~OpenGLContext.physics.cooking`
  -- collision shapes, cooked from nodes and triangles.
* :mod:`~OpenGLContext.physics.types` -- materials, collision filters,
  characters' capabilities and state, poses, the world's counts and the
  engine's description.
* :mod:`~OpenGLContext.physics.engine` -- the interface the service steps a
  world through, and :func:`~OpenGLContext.physics.engine.make_engine`;
  :mod:`~OpenGLContext.physics.joltengine` is the default engine, and
  :mod:`~OpenGLContext.physics.omiengine` the deprecated omi engine (the
  ``omi`` extra) with its :mod:`~OpenGLContext.physics.worker` and
  :mod:`~OpenGLContext.physics.runtime`.
* :mod:`~OpenGLContext.physics.debugdraw` -- the wireframe overlay of the
  bodies' proxies.
* :mod:`~OpenGLContext.physics.omigltf` and :mod:`~OpenGLContext.physics.gltf_world`
  -- glTF's OMI physics bodies, and a loaded scenegraph's triangles.
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
