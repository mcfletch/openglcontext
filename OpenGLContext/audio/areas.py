"""How loud an area's sound is at the listener's position.

An area's ambience is a looping ``global`` source heard only while the listener
is in the area, fading over a margin so that walking out of an area fades its
sound rather than cutting it. See ``docs/audio.rst``.

A scene declares its areas as zones (:mod:`OpenGLContext.scenegraph.zone`),
and :func:`apply_zones` is what the render pass calls each frame to set every
zone-controlled emitter's gain and the reverb from where the listener is.
:func:`box_gain` is the same idea for an application that keeps its areas in
code: it gives the gain for an axis-aligned box, and the application sets its
source's ``gain`` from it.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from numpy.typing import ArrayLike

__all__ = ['box_gain', 'apply_zones']


def box_gain(position: Sequence[float], centre: Sequence[float],
             half_size: Sequence[float], margin: float = 3.0) -> float:
    """1.0 inside an axis-aligned box, falling linearly to 0.0 ``margin`` outside it.

    ``position`` is the listener's, in world coordinates; a homogeneous
    ``(x, y, z, 1)`` such as ``ViewPlatform.position`` is accepted.  ``centre``
    and ``half_size`` are the box's, and ``margin`` is in metres.  The distance
    outside the box is taken on the axis where it is largest, so a listener
    outside on any one axis is outside.  A ``margin`` of 0 is a hard edge.
    """
    offset = np.abs(np.asarray(position, dtype='d')[:3] - np.asarray(centre, dtype='d'))
    outside = float((offset - np.asarray(half_size, dtype='d')).max())
    if outside <= 0.0:
        return 1.0
    if margin <= 0.0:
        return 0.0
    return float(min(1.0, max(0.0, 1.0 - outside / margin)))


def apply_zones(engine: Any, emitters: Sequence[Any], zones: Sequence[Any],
                position: ArrayLike, table: Any = None) -> None:
    """Set each zone-controlled emitter's gain, and the reverb, for a listener at ``position``.

    ``emitters`` are the scene's :class:`~OpenGLContext.scenegraph.audio.AudioEmitter`
    nodes and ``zones`` the frame's placed zones. An emitter a zone names
    plays at the share of the zones naming it that the listener is in, so it
    fades over a zone's ``blend``; one no zone names is left at full gain. The
    engine's reverb takes the level, decay and damping of the zones the
    listener is in, mixed by their shares, and none outside every zone.
    ``table``, a :class:`~OpenGLContext.passes.zonelayers.ZoneTable` of
    ``zones``, weighs every zone at the listener in one pass.
    """
    from OpenGLContext.passes import zonelayers
    from OpenGLContext.scenegraph.zone import AUDIO

    def named(setting: Any) -> Sequence[int]:
        return [id(emitter) for emitter in getattr(setting, 'emitters', None) or ()]

    controlled: set = set()
    for zone in zones:
        setting = zone.setting(AUDIO)
        if setting is not None and bool(setting.enabled):
            controlled.update(named(setting))
    weights = zonelayers.point_weights(table, position) if table is not None else None
    shares = (zonelayers.camera_shares(zones, position, AUDIO, named, weights)
              if controlled else {})
    for emitter in emitters:
        key = id(emitter)
        wanted = float(shares.get(key, 0.0)) if key in controlled else 1.0
        if getattr(emitter, 'zoneGain', 1.0) != wanted:
            emitter.zoneGain = wanted
    reverb = zonelayers.reverb_at(zones, position, weights)
    target = getattr(engine, 'reverb', None)
    if target is not None:
        target.level = reverb.level
        target.decay = reverb.decay
        target.damping = reverb.damping
