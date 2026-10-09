"""Which Coordinate nodes something deforms, and the deformer each geometry reading one draws through

A geometry draws the points of its `coord`. Where something else moves those
points as it is drawn -- an X3D humanoid its `skinCoord` by the joints, an
`HAnimSegment` its `coord` by its displacers -- the mover registers here as
the coordinates' :class:`Deformer`, and a geometry reading them (an
`IndexedFaceSet`, the triangle and quad sets) is drawn, bounded and shadowed
through it instead of from its own arrays. The document's points are not
written: what is deformed is the drawing.

A deformed geometry is drawn on its own, never in an instanced group, since
each one's pose is its own (:func:`deformer_for` is what the batch keys ask).
"""
from __future__ import annotations

import weakref
from typing import Any, Optional, Protocol

from vrml import cache

__all__ = ['Deformer', 'deformer_for', 'register', 'unregister']


class Deformer(Protocol):
    """What draws a geometry whose coordinates are deformed"""

    def render(self, geometry: Any, visible: int, lit: int, textured: int,
               transparent: int, mode: Any) -> int:
        """Draw `geometry` deformed, as its own `render` would"""

    def boundingVolume(self, geometry: Any, mode: Any) -> Any:
        """The bounds of `geometry` as it is deformed now"""


_DEFORMERS: 'weakref.WeakKeyDictionary[Any, Deformer]' = weakref.WeakKeyDictionary()


def register(coord: Any, deformer: Deformer) -> None:
    """Draw every geometry reading `coord` through `deformer`

    The bounds already worked out from the points are dropped, so the shapes
    drawing them are bounded by the deformer from now on.
    """
    if _DEFORMERS.get(coord) is deformer:
        return
    _DEFORMERS[coord] = deformer
    _forget_bounds(coord)


def unregister(coord: Any, deformer: Deformer) -> None:
    """Stop drawing `coord` through `deformer`, where that is what it is drawn through"""
    if _DEFORMERS.get(coord) is deformer:
        del _DEFORMERS[coord]
        _forget_bounds(coord)


def deformer_for(geometry: Any) -> Optional[Deformer]:
    """What deforms the coordinates `geometry` reads; None where nothing does"""
    if not _DEFORMERS:
        return None
    coord = getattr(geometry, 'coord', None)
    if not coord:
        return None
    try:
        return _DEFORMERS.get(coord)
    except TypeError:       # a value the dictionary cannot hold is held by nothing
        return None


def _forget_bounds(coord: Any) -> None:
    holder = cache.CACHE.getHolder(coord, key='boundingVolume')
    if holder is not None:
        holder.clear()
