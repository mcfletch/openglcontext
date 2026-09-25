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

import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Set

import numpy as np
from numpy.typing import ArrayLike

from OpenGLContext.scenegraph import zones as zonemath

if TYPE_CHECKING:
    from OpenGLContext.passes.zonelayers import Reverb
    from OpenGLContext.scenegraph.zone import PlacedZone

__all__ = ['box_gain', 'apply_zones']


def box_gain(position: Sequence[float], centre: Sequence[float],
             half_size: Sequence[float], margin: float = 3.0) -> float:
    """1.0 inside an axis-aligned box, falling smoothly to 0.0 ``margin`` outside it.

    ``position`` is the listener's, in world coordinates; a homogeneous
    ``(x, y, z, 1)`` such as ``ViewPlatform.position`` is accepted.  ``centre``
    and ``half_size`` are the box's, and ``margin`` is in metres.  This is a
    box zone's weight with ``margin`` as its blend: the distance is to the
    nearest point of the box, and the fall is the smoothstep a zone's blend
    uses (:func:`OpenGLContext.scenegraph.zones.weight`), a half at half the
    margin.  A ``margin`` of 0 is a hard edge.
    """
    offset = np.asarray(position, dtype='d')[:3] - np.asarray(centre, dtype='d')
    distance = zonemath._box(offset, np.abs(np.asarray(half_size, dtype='d')))
    return float(zonemath.weight(distance, float(margin)))


@dataclass
class _ReverbOverZones:
    """The application's own reverb on an engine, and what the zones last set."""

    base: 'Reverb'
    written: Optional['Reverb'] = None


#: Each engine whose reverb the zones are laid over; see :func:`apply_zones`.
_reverbs: "weakref.WeakKeyDictionary[Any, _ReverbOverZones]" = weakref.WeakKeyDictionary()


def apply_zones(engine: Any, emitters: Sequence[Any], zones: Sequence[Any],
                position: ArrayLike, table: Any = None) -> None:
    """Set each zone-controlled emitter's gain, and the reverb, for a listener at ``position``.

    ``emitters`` are the scene's :class:`~OpenGLContext.scenegraph.audio.AudioEmitter`
    nodes and ``zones`` the frame's placed zones. An emitter a zone names
    plays at the share of the zones naming it that the listener is in, so it
    fades over a zone's ``blend``; one no zone names is left at full gain.
    ``table``, a :class:`~OpenGLContext.passes.zonelayers.ZoneTable` of
    ``zones``, weighs every zone at the listener in one pass.

    The engine's reverb is touched only while some zone has a
    ``ZoneReverb``. The reverb the application had set is kept, and the
    zones the listener is in are laid over it by their shares
    (:func:`~OpenGLContext.passes.zonelayers.reverb_at`); outside them it is
    the application's. A value the application sets while the zones are
    applied is taken as its own from then on. When no zone has a reverb any
    more, the application's is put back.
    """
    from OpenGLContext.passes import zonelayers
    from OpenGLContext.scenegraph.zone import AUDIO

    def named(setting: Any) -> Sequence[Any]:
        return list(getattr(setting, 'emitters', None) or ())

    controlled: Set[Any] = set()
    for zone in zones:
        setting = zone.setting(AUDIO)
        if setting is not None and bool(setting.enabled):
            controlled.update(named(setting))
    weights = zonelayers.point_weights(table, position) if table is not None else None
    shares = (zonelayers.camera_shares(zones, position, AUDIO, named, weights)
              if controlled else {})
    for emitter in emitters:
        wanted = float(shares.get(emitter, 0.0)) if emitter in controlled else 1.0
        if getattr(emitter, 'zoneGain', 1.0) != wanted:
            emitter.zoneGain = wanted
    _lay_reverb(engine, zones, position, weights)


def _lay_reverb(engine: Any, zones: Sequence[Any], position: ArrayLike,
                weights: Optional[Dict[PlacedZone, float]]) -> None:
    """The zones' reverb over the application's, on ``engine``; see :func:`apply_zones`."""
    from OpenGLContext.passes import zonelayers
    from OpenGLContext.scenegraph.zone import REVERB
    target = getattr(engine, 'reverb', None)
    if target is None:
        return
    held = _reverbs.get(engine)
    reverberant = any(zone.setting(REVERB) is not None for zone in zones)
    if held is None:
        if not reverberant:
            return
        held = _reverbs[engine] = _ReverbOverZones(_reading(target))
    elif _reading(target) != held.written:
        held.base = _reading(target)
    if not reverberant:
        _write(target, held.base)
        del _reverbs[engine]
        return
    _write(target, zonelayers.reverb_at(zones, position, weights, held.base))
    held.written = _reading(target)


def _reading(target: Any) -> 'Reverb':
    from OpenGLContext.passes.zonelayers import Reverb
    return Reverb(float(target.level), float(target.decay), float(target.damping))


def _write(target: Any, reverb: 'Reverb') -> None:
    target.level = reverb.level
    target.decay = reverb.decay
    target.damping = reverb.damping
