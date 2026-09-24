"""Mirrors an artist marked in a model: the ``mirror`` kind.

Nothing in glTF says a surface reflects the scene rather than the sky.
``OGLC_hook`` does (:mod:`OpenGLContext.loaders.gltf.hooks`), and this is what
the engine makes of it. The tag goes in one of two places, and they mean
different things.

On a **material**, every surface drawn with that material is a mirror, each in
its own plane, and the material shades the reflection: its base colour tints
it, its metalness and roughness weigh it through the same terms the sky's
reflection goes through, and its normal map breaks it up. A silvered mirror is
metallic 1, roughness 0; a polished floor is a dielectric with low roughness,
which reflects faintly looking down and strongly at a glance::

    OGLC_hook = {"kind": "mirror", "scale": 0.5, "interval": 2, "priority": 1.0}

On an **object**, every surface of it shows the reflection and nothing else:
the object's own materials are set aside for one that draws the mirrored scene
as it is, with the sky where there is nothing to mirror.

``OGLC_hook = "mirror"`` is the shorthand with every default. The parameters
are :class:`~OpenGLContext.scenegraph.reflector.PlanarReflector`'s fields, all
optional:

``scale``
    Resolution as a share of the mirror's rectangle on screen, each way.
    Default 0.5.
``interval``
    The most frames the reflection goes without being drawn again. Default 3.
``priority``
    Weight against the other mirrors in view when the frame's budget is short.
    Default 1.
``distortion``
    View widths of offset per unit of the surface normal's tilt from the
    plane: how far a normal map breaks the reflection up. Default 0.
``replace``
    Whether the surface shows only the reflection. False on a material, True
    on an object; either may say otherwise.

A surface only reflects the scene if it is flat: a mesh whose points stand off
its plane by more than 1% of its size reports so and reflects the sky.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.shape import Shape

log = logging.getLogger(__name__)

__all__ = ['KIND', 'PARAMETERS', 'reflector_for', 'hook_for', 'mirror_material',
           'mirror_hook']

#: What a document names this hook.
KIND = 'mirror'

#: Each parameter a tag may give, and the type its value is read as.
PARAMETERS: Dict[str, type] = {
    'scale': float, 'interval': int, 'priority': float, 'distortion': float,
    'replace': bool,
}


def reflector_for(params: Dict[str, Any], replace: bool = False) -> PlanarReflector:
    """The reflector a tag's parameters describe.

    A value that cannot be read as its parameter's type is reported and left
    at the default: a misspelling in a custom property is a model to load
    rather than a file to refuse.
    """
    values: Dict[str, Any] = {'replace': replace}
    for name, kind in PARAMETERS.items():
        if name not in params:
            continue
        raw = params[name]
        try:
            if kind is bool:
                value: Any = raw if isinstance(raw, bool) else str(raw).strip().lower() in (
                    '1', 'true', 'yes', 'on')
            elif isinstance(raw, bool):
                raise ValueError(raw)
            else:
                value = kind(float(raw)) if kind is int else kind(raw)
        except (TypeError, ValueError):
            log.warning('the mirror %s %r is not a number; it is left at its '
                        'default', name, raw)
            continue
        values[name] = value
    return PlanarReflector(**values)


def hook_for(reflector: PlanarReflector) -> Dict[str, Any]:
    """The ``OGLC_hook`` block that loads back as ``reflector``.

    Only what differs from a default is written, so a plain mirror is
    written as plainly as an artist would tag one.
    """
    written: Dict[str, Any] = {'kind': KIND}
    default = PlanarReflector()
    for name, kind in PARAMETERS.items():
        value = getattr(reflector, name)
        if value != getattr(default, name):
            written[name] = kind(value)
    return written


def mirror_material(reflector: PlanarReflector) -> PBRMaterial:
    """What an object that shows only its reflection is drawn with."""
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=1.0, roughness=0.0,
                       reflector=reflector)


def _shapes(nodes: Any) -> Iterator[Shape]:
    """Every shape under ``nodes``, however deep."""
    for node in nodes or ():
        if isinstance(node, Shape):
            yield node
            continue
        for name in ('children', 'level', 'choice'):
            yield from _shapes(getattr(node, name, None))


def mirror_hook(ctx: "hooks.HookContext") -> None:
    """Make a tagged material or object a mirror, and leave it where it is."""
    if ctx.at == 'material':
        if not getattr(ctx.material, 'reflector', None):
            ctx.material.reflector = reflector_for(ctx.params)
        return None
    material = mirror_material(reflector_for(ctx.params, replace=True))
    for shape in _shapes(ctx.children):
        shape.appearance.material = material
        if hasattr(shape.geometry, 'material'):
            shape.geometry.material = material
    return None


# Not shareable: an object tagged a mirror has its own shapes changed, and a
# second object built from the same mesh is not a mirror unless it says so.
hooks.register(KIND, mirror_hook, shareable=False)
