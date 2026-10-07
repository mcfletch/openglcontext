"""Which rules light a scene: X3D's, or the engine's -- no GL

X3D's rules (ISO/IEC 19775-1, 17.2.2): a ``Material`` is drawn by the Phong
equation, an appearance with no material is unlit, the headlight is on unless
a NavigationInfo turns it off, and the only ambient light is each light's
``ambientIntensity``. The engine's: a ``Material`` is converted to
metallic-roughness factors, lit in linear light with the built-in studio
environment and a flat fill, and the headlight lights a scene with no lights
of its own.

``ContextDefinition.lighting`` chooses (default ``OPENGLCONTEXT_LIGHTING``):

- ``auto`` -- a scene, or a node, read from a VRML97 or X3D document is lit by
  X3D's rules, and one built in code by the engine's;
- ``x3d`` and ``engine`` -- every scene by those rules.

The render pass says which it is drawing with (:func:`use`) as it sets up each
frame's lights, and the material views ask :func:`x3d_lit`.
"""
from typing import Any

from vrml import protofunctions
from vrml.x3d.scene import X3DScene

__all__ = ['MODELS', 'in_document', 'model', 'scene_x3d_lit', 'use', 'x3d_lit']

#: The choices of ``ContextDefinition.lighting``.
MODELS = ('auto', 'x3d', 'engine')

_current = 'auto'


def use(chosen: str) -> None:
    """Light what is drawn from now on by `chosen` (:data:`MODELS`)"""
    global _current
    if chosen not in MODELS:
        raise ValueError('lighting is one of %s, not %r' % (MODELS, chosen))
    _current = chosen


def model() -> str:
    """The rules what is drawn now is lit by (:data:`MODELS`)"""
    return _current


def in_document(node: Any) -> bool:
    """Whether `node` belongs to a scene read from a VRML97 or X3D document"""
    return node is not None and isinstance(protofunctions.root(node), X3DScene)


def x3d_lit(node: Any) -> bool:
    """Whether `node` is lit by X3D's rules under the rules in use"""
    if _current == 'auto':
        return in_document(node)
    return _current == 'x3d'


def scene_x3d_lit(scene: Any, chosen: str) -> bool:
    """Whether `scene` is lit by X3D's rules under `chosen`"""
    if chosen == 'auto':
        return isinstance(scene, X3DScene)
    return chosen == 'x3d'
