"""Rigid bodies, characters and joints for a context, over the :mod:`omi_physics` engine.

Every context has a physics service, ``context.physics``
(:class:`~OpenGLContext.physics.service.Physics`), made on first use. A game
adds bodies, characters and joints through it and reads them through the handles
it returns; the world steps itself. The names a game needs are importable from
this package::

    from OpenGLContext.physics import CharacterCapabilities, Material, Proxy

They are loaded on first use, so importing the package imports neither the
service nor :mod:`omi_physics`. The modules:

* :mod:`~OpenGLContext.physics.service` -- the service: adding, removing,
  queries, events, the frame.
* :mod:`~OpenGLContext.physics.body`, :mod:`~OpenGLContext.physics.character`
  and :mod:`~OpenGLContext.physics.joints` -- the handles it returns.
* :mod:`~OpenGLContext.physics.proxy` -- collision shapes, cooked from nodes.
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
    from omi_physics.character import CharacterCapabilities
    from omi_physics.model import CollisionFilter, Material

    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.joints import Joint
    from OpenGLContext.physics.proxy import Proxy
    from OpenGLContext.physics.service import Physics
    from OpenGLContext.physics.settings import PhysicsDefinition

#: Each exported name and the module it is defined in.
_HOMES = {
    'Body': 'OpenGLContext.physics.body',
    'Character': 'OpenGLContext.physics.character',
    'CharacterCapabilities': 'omi_physics.character',
    'CollisionFilter': 'omi_physics.model',
    'Joint': 'OpenGLContext.physics.joints',
    'Material': 'omi_physics.model',
    'Physics': 'OpenGLContext.physics.service',
    'PhysicsDefinition': 'OpenGLContext.physics.settings',
    'Proxy': 'OpenGLContext.physics.proxy',
}

__all__ = ['Body', 'Character', 'CharacterCapabilities', 'CollisionFilter', 'Joint', 'Material', 'Physics',
           'PhysicsDefinition', 'Proxy']


def __getattr__(name: str) -> Any:
    home = _HOMES.get(name)
    if home is None:
        raise AttributeError('module %r has no attribute %r' % (__name__, name))
    value = getattr(importlib.import_module(home), name)
    globals()[name] = value
    return value
