"""Water an artist marked in a model: the ``water`` kind.

A lake modelled in Blender is a flat sheet with a material on it, and nothing in
glTF says that the sheet is water. ``OGLC_hook`` does
(:mod:`OpenGLContext.loaders.gltf.hooks`), and this is what the engine makes of
it: a custom property on the material datablock, and the surface loads moving.

    OGLC_hook = {"kind": "water", "style": "choppy", "depth": 6.0}

The shorthand is the kind on its own, ``OGLC_hook = "water"``, which is a pond.
Four parameters, all optional:

``style``
    ``still``, ``breeze``, ``flowing``, ``choppy`` or ``lake``, or an object
    spelling out :class:`~OpenGLContext.scenegraph.water.surface.WaterStyle`
    over one of them -- ``amplitude``, ``wavelength``, ``speed``,
    ``steepness``, ``ripple``, ``flow`` -- for water that is none of the five.
    ``breeze`` is a pond or small lake seen from its bank; ``lake`` is open
    water seen from a distance.
``material``
    ``keep``, the default, shades the surface with the material the file
    carries, so what the artist authored is what is drawn. ``engine`` takes
    :func:`~OpenGLContext.scenegraph.water.surface.water_material` instead.
``medium``
    ``water``, ``slime`` or ``lava``: what being inside it is like
    (:mod:`OpenGLContext.scenegraph.water.medium`). Lava is this hook with
    another medium and another material, which is why there is no second kind.
    A name :data:`~OpenGLContext.scenegraph.water.medium.MEDIA` does not have
    is reported and is water.
``depth``
    How far below the surface the body reaches, in metres, at least 0. A
    surface has no thickness, so a sheet with no ``depth`` bounds a box nothing
    can be inside of except exactly at the waterline.

A value that is no finite number is reported once and left at its default.

What it leaves behind is one :class:`WaterBody` per tagged primitive in
``scene.hook_data['water']``: the mesh whose wave a frame advances, the style it
moves with, and the :class:`~OpenGLContext.scenegraph.water.volumes.Volume` that
says where it is. A walking context is submerged by handing those volumes to
:class:`~OpenGLContext.scenegraph.water.volumes.Volumes`.

The wave itself costs nothing per frame -- the card holds the field and reads
the style and the time off the geometry -- but something has to say what time
it is.
:meth:`~OpenGLContext.loaders.gltf.scene.GLTFScene.advance` is that, and the
viewer calls it from its idle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from OpenGLContext.loaders.documentvalues import DocumentValues
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import WATER as WATER_REFLECTOR
from OpenGLContext.scenegraph.water.medium import MEDIA, WATER
from OpenGLContext.scenegraph.water.surface import (
    BREEZE, CHOPPY, FLOWING, LAKE, STILL, WaterStyle, water_material,
)
from OpenGLContext.scenegraph.water.volumes import Volume

log = logging.getLogger(__name__)

__all__ = ['KIND', 'STYLES', 'STYLE_RANGES', 'WaterBody', 'style_for',
           'water_hook', 'advance']

#: What a document names this hook.
KIND = 'water'

#: The motions a style may be named by. A document may also spell one out in
#: full, since water is a continuum and five names are a convenience rather
#: than the set of things water does.
STYLES: dict[str, WaterStyle] = {
    'still': STILL, 'breeze': BREEZE, 'flowing': FLOWING, 'choppy': CHOPPY,
    'lake': LAKE,
}


@dataclass
class WaterBody:
    """One tagged surface: what moves, how, and the space it bounds."""

    mesh: PBRMesh
    style: WaterStyle
    volume: Volume

    @property
    def medium(self) -> str:
        """What being inside this body is like."""
        return str(self.volume.medium)


def style_for(named: Any, values: Optional[DocumentValues] = None) -> WaterStyle:
    """The motion a tag asks for: one of :data:`STYLES`, or one written out.

    A name nothing answers to is a pond, and said so once -- a misspelling in a
    custom property is a model to load rather than a file to refuse. So is a
    written-out value that is no finite number, and one outside
    :data:`STYLE_RANGES` is the nearer end of its range. ``values`` reports
    each problem once for a whole load; without one, once for this call.
    """
    values = values if values is not None else DocumentValues(logger=log)
    if isinstance(named, str):
        style = STYLES.get(named.strip().lower())
        if style is None:
            values.warn('%r is not a water style; %s are, and this one is '
                        'drawn still' % (named, ', '.join(sorted(STYLES))))
            return STILL
        return style
    if isinstance(named, dict):
        return _written_out(named, values)
    return STILL


#: The range each written-out style field is held to, ``(minimum, maximum)``
#: with None for an open end. A wavelength or a ripple is at least a
#: centimetre, since the wave divides by both.
STYLE_RANGES: dict[str, tuple[Optional[float], Optional[float]]] = {
    'amplitude': (0.0, None), 'wavelength': (0.01, None), 'speed': (None, None),
    'steepness': (0.0, None), 'ripple': (0.01, None),
}


def _written_out(fields: dict[str, Any], values: DocumentValues) -> WaterStyle:
    """A style spelled out field by field, over whichever one it names."""
    base = style_for(fields.get('style', 'still'), values)
    found: dict[str, Any] = {}
    for name, (minimum, maximum) in STYLE_RANGES.items():
        if fields.get(name) is not None:
            found[name] = values.number(fields[name], float(getattr(base, name)),
                                        'the water %s' % (name,),
                                        minimum=minimum, maximum=maximum)
    if fields.get('flow') is not None:
        found['flow'] = values.vector(fields['flow'], tuple(base.flow),
                                      'the water flow', length=2)
    if not found:
        return base
    return base.varied(name=str(fields.get('name') or base.name), **found)


def _body_volume(ctx: "hooks.HookContext", medium: str,
                 depth: float) -> Optional[Volume]:
    """The space one tagged primitive bounds, where it is in the world.

    A surface authored as a sheet is a box with no height, so ``depth`` is what
    turns it into something a swimmer is inside of: the box reaches that far
    below whatever the lowest point of the surface is.
    """
    placed = ctx.world_bounds()
    if placed is None:                       # pragma: no cover - needs a primitive
        return None
    low, high = placed
    return Volume(minimum=(float(low[0]), float(low[1]) - depth, float(low[2])),
                  maximum=(float(high[0]), float(high[1]), float(high[2])),
                  medium=medium)


def water_hook(ctx: "hooks.HookContext") -> None:
    """Make a tagged primitive a body of water, and leave it where it is.

    The ``Shape`` the loader built is kept: water is not a different kind of
    node, it is a surface that moves, and what moves it is the style in the
    mesh's ``waveStyle`` field and the time the render pass reads beside it.
    Each tagged primitive is given its own copy of the style it names.
    """
    if ctx.at != 'material':
        # A node-level tag says the *object* is a body of water. The surface is
        # what carries the wave, so there is nothing to do for the group that
        # holds it; a game wanting more registers a kind of its own.
        return None
    mesh, shape, material = ctx.mesh, ctx.shape, ctx.material
    if mesh is None or shape is None or material is None:  # pragma: no cover - the loader passes all three
        return None
    values = ctx.values
    # The document's own copy: a named style is a node every sheet built with
    # it shares, and a loaded model's water is changed without changing it.
    style = style_for(ctx.params.get('style', 'still'), values).varied()
    mesh.waveStyle = style
    mesh.wave_time = 0.0
    if values.choice(ctx.params.get('material'), 'keep', 'the water material',
                     ('keep', 'engine')) == 'engine':
        engine = water_material()
        mesh.material = engine
        shape.appearance.material = engine
    elif not getattr(material, 'reflector', None):
        # Water mirrors the shore, whatever material the artist gave it.
        material.reflector = WATER_REFLECTOR
    medium = values.choice(ctx.params.get('medium'), WATER, 'the water medium',
                           MEDIA)
    depth = values.number(ctx.params.get('depth'), 0.0, 'the water depth',
                          minimum=0.0)
    volume = _body_volume(ctx, medium, depth)
    if volume is not None:
        ctx.collect(WaterBody(mesh=mesh, style=style, volume=volume))
    return None


def advance(bodies: list[WaterBody], when: float) -> bool:
    """Move every body's surface to ``when``, in seconds since the scene began.

    Returns whether anything moved. Still water has its ripple in the normals
    and its surface exactly at its waterline, so a scene of ponds asks for no
    redraw at all.
    """
    moved = False
    for body in bodies:
        if body.style.moving():
            body.mesh.wave_time = float(when)
            moved = True
    return moved


# Not shareable: each node carries its own box round where that copy of the
# surface stands, so two lakes cut from one mesh are two bodies of water.
hooks.register(KIND, water_hook, shareable=False, advance=advance)
