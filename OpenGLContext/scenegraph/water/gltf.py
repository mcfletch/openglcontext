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
``depth``
    How far below the surface the body reaches, in metres. A surface has no
    thickness, so a sheet with no ``depth`` bounds a box nothing can be inside
    of except exactly at the waterline.

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
from typing import Any, Dict, List, Optional, Sequence

from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.water.medium import WATER
from OpenGLContext.scenegraph.water.surface import (
    BREEZE, CHOPPY, FLOWING, LAKE, STILL, WaterStyle, water_material,
)
from OpenGLContext.scenegraph.water.volumes import Volume

log = logging.getLogger(__name__)

__all__ = ['KIND', 'STYLES', 'WaterBody', 'style_for', 'water_hook', 'advance']

#: What a document names this hook.
KIND = 'water'

#: The motions a style may be named by. A document may also spell one out in
#: full, since water is a continuum and five names are a convenience rather
#: than the set of things water does.
STYLES: Dict[str, WaterStyle] = {
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


def style_for(named: Any) -> WaterStyle:
    """The motion a tag asks for: one of :data:`STYLES`, or one written out.

    A name nothing answers to is a pond, and said so once -- a misspelling in a
    custom property is a model to load rather than a file to refuse.
    """
    if isinstance(named, str):
        style = STYLES.get(named.strip().lower())
        if style is None:
            log.warning('%r is not a water style; %s are, and this one is '
                        'drawn still', named, ', '.join(sorted(STYLES)))
            return STILL
        return style
    if isinstance(named, dict):
        return _written_out(named)
    return STILL


def _written_out(fields: Dict[str, Any]) -> WaterStyle:
    """A style spelled out field by field, over whichever one it names."""
    base = style_for(fields.get('style', 'still'))
    values: Dict[str, Any] = {}
    for name in ('amplitude', 'wavelength', 'speed', 'steepness', 'ripple'):
        if fields.get(name) is not None:
            values[name] = float(fields[name])
    flow = fields.get('flow')
    if isinstance(flow, Sequence) and len(flow) == 2:
        values['flow'] = (float(flow[0]), float(flow[1]))
    if not values:
        return base
    return base.varied(name=str(fields.get('name') or base.name), **values)


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
    """
    if ctx.at != 'material':
        # A node-level tag says the *object* is a body of water. The surface is
        # what carries the wave, so there is nothing to do for the group that
        # holds it; a game wanting more registers a kind of its own.
        return None
    style = style_for(ctx.params.get('style', 'still'))
    ctx.mesh.waveStyle = style
    ctx.mesh.wave_time = 0.0
    if str(ctx.params.get('material', 'keep')).strip().lower() == 'engine':
        engine = water_material()
        ctx.mesh.material = engine
        ctx.shape.appearance.material = engine
    volume = _body_volume(ctx, str(ctx.params.get('medium') or WATER),
                          float(ctx.params.get('depth') or 0.0))
    if volume is not None:
        ctx.collect(WaterBody(mesh=ctx.mesh, style=style, volume=volume))
    return None


def advance(bodies: List[WaterBody], when: float) -> bool:
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
