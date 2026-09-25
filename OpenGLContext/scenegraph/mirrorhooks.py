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
    Default 0.5, from 0.05 to 1.
``interval``
    The most frames the reflection goes without being drawn again. Default 3,
    at least 1.
``priority``
    Weight against the other mirrors in view when the frame's budget is short.
    Default 1, at least 0.
``distortion``
    Offset per unit of the surface normal's tilt from the plane, in widths
    (and heights) of the mirror's view: how far a normal map breaks the
    reflection up. Default 0, at most 1.
``reflectance``
    The share of the light the mirror reflects. Default 0.97, from 0 to 1.
``replace``
    Whether the surface shows only the reflection. False on a material, True
    on an object; either may say otherwise.

A surface only reflects the scene if it is flat: a mesh whose points stand off
its plane by more than 1% of its size reports so and reflects the sky.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

from OpenGLContext.loaders.documentvalues import DocumentValues, JSONObject
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import LIMITS, PlanarReflector
from OpenGLContext.scenegraph.shape import Shape

log = logging.getLogger(__name__)

__all__ = ['KIND', 'PARAMETERS', 'reflector_for', 'hook_for', 'mirror_material',
           'mirrored', 'mirror_hook']

#: What a document names this hook.
KIND = 'mirror'

#: Each parameter a tag may give, and the type its value is read as. A
#: number is held to :data:`~OpenGLContext.scenegraph.reflector.LIMITS`.
PARAMETERS: Dict[str, type] = {
    'scale': float, 'interval': int, 'priority': float, 'distortion': float,
    'reflectance': float, 'replace': bool,
}


def reflector_for(params: JSONObject, replace: bool = False,
                  values: Optional[DocumentValues] = None) -> PlanarReflector:
    """The reflector a tag's parameters describe.

    A value that cannot be read as its parameter's type, or is no finite
    number, is reported and left at the default; one outside
    :data:`~OpenGLContext.scenegraph.reflector.LIMITS` is reported and is the
    nearer end of the range. A misspelling in a custom property is a model to
    load rather than a file to refuse. ``values`` reports each problem once
    for a whole load; without one, once for this call.
    """
    values = values if values is not None else DocumentValues(logger=log)
    default = PlanarReflector()
    found: Dict[str, Any] = {'replace': values.flag(
        params.get('replace'), replace, 'the mirror replace')}
    for name, kind in PARAMETERS.items():
        if kind is bool:
            continue
        minimum, maximum = LIMITS[name]
        what = 'the mirror %s' % (name,)
        if kind is int:
            found[name] = values.integer(
                params.get(name), getattr(default, name), what,
                minimum=None if minimum is None else int(minimum),
                maximum=None if maximum is None else int(maximum))
        else:
            found[name] = values.number(params.get(name), getattr(default, name),
                                        what, minimum=minimum, maximum=maximum)
    return PlanarReflector(**found)


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


def mirrored(node: Any, material: PBRMaterial) -> Any:
    """``node`` with every shape under it drawn with ``material``, however deep.

    A shape is replaced by a copy that shares its geometry, with an appearance
    of its own: the loader hands every node on one glTF mesh the same shapes,
    and another node on that mesh is no mirror unless it is tagged too. The
    groups, levels and choices above the shapes are the tagged node's own, and
    have their lists replaced in place.
    """
    if isinstance(node, Shape):
        made = copy.copy(node)
        appearance = copy.copy(node.appearance) if node.appearance else Appearance()
        appearance.material = material
        made.appearance = appearance
        return made
    for name in ('children', 'level', 'choice'):
        nodes = getattr(node, name, None)
        if nodes:
            setattr(node, name, [mirrored(child, material) for child in nodes])
    return node


def mirror_hook(ctx: "hooks.HookContext") -> None:
    """Make a tagged material or object a mirror, and leave it where it is."""
    if ctx.at == 'material':
        if ctx.material is not None and not getattr(ctx.material, 'reflector', None):
            ctx.material.reflector = reflector_for(ctx.params, values=ctx.values)
        return None
    material = mirror_material(reflector_for(ctx.params, replace=True,
                                             values=ctx.values))
    ctx.children[:] = [mirrored(child, material) for child in ctx.children]
    return None


hooks.register(KIND, mirror_hook, shareable=False)
