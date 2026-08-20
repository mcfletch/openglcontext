"""Putting a context inside a medium: the view and the mix.

Being under water is **not a coloured pane over the screen**. It is a medium
with depth in it -- what is in your hands is clear, the far wall is not -- and a
flat tint treats them alike. So the view is closed in with a
:class:`~OpenGLContext.scenegraph.fog.Fog`, on the exponential curve, which the
render pass binds like any other; and the mix is damped through the whole-mix
low-pass the audio engine already carries.

Every part is optional. A viewer between worlds has no volumes and a machine
with no sound has no engine, and neither is a reason for a frame to fail.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from OpenGLContext.scenegraph.fog import Fog
from OpenGLContext.scenegraph.water.medium import Medium, medium_for

__all__ = ['medium_fog', 'apply', 'muffle_for', 'submerge']


def medium_fog() -> Fog:
    """A fog node for a context to hold, starting switched off.

    One node, reused: it is bound into the scene once and its fields are
    written as the body goes in and out, so entering water is a field change
    rather than a scenegraph edit. Range zero is the specification's own way of
    saying "no fog", which is what dry air wants.
    """
    return Fog(visibilityRange=0.0, fogType='EXPONENTIAL')


def apply(fog: Fog, name: str) -> Optional[Medium]:
    """Set a fog node to what being inside ``name`` looks like.

    An empty name is dry air and switches the fog off; nothing else does, so a
    substance this engine has no entry for still fogs.
    """
    medium = medium_for(name)
    if medium is None:
        fog.visibilityRange = 0.0
        return None
    fog.color = medium.color
    fog.visibilityRange = medium.visibility
    fog.fogType = 'EXPONENTIAL'
    return medium


def muffle_for(name: str) -> float:
    """How much of the mix's high end ``name`` takes, 0 for dry air."""
    medium = medium_for(name)
    return medium.muffle if medium is not None else 0.0


def submerge(context: Any, volumes: Any, point: Sequence[float]) -> str:
    """Put a context's view and mix into whatever is at a point.

    Called once a frame with the body's position; answers the substance it
    found, so a caller can report it or charge for it.

    ``volumes`` is anything that answers ``medium_at(point)`` with a substance
    name or ``''`` -- :class:`~OpenGLContext.scenegraph.water.volumes.Volumes`,
    or a game's own, because how a world *finds* its water is the world's
    question and a BSP's contents flags and a track's lake are not the same
    one. None is a world with no water in it.
    """
    from OpenGLContext.audio import scene as audioscene

    name = volumes.medium_at(point) if volumes is not None else ''
    fog = getattr(context, 'fog', None)
    if fog is not None:
        apply(fog, name)
    # The engine the context already has, and never a new one: opening a device
    # in order to muffle a silence would make walking into a pool the one thing
    # that starts the audio thread on a machine with no sound.
    engine = audioscene.existing_engine(context)
    if engine is not None:
        engine.muffle = muffle_for(name)
    return name
