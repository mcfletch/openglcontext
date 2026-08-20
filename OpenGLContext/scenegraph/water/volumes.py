"""Where the media are, and what is at a point.

A liquid is a *volume*: its surface is drawn, but what decides whether a body
is in it is whether the body is inside the space it bounds. This is that space,
as boxes, and the one question anything asks of it.

**How a world finds its volumes stays with the world.** A map's contents flags
and a track's lake are not the same question and never will be, so nothing here
reads a file: a caller works out where the water is and hands over the boxes.
A box is the conservative answer at the edge of a sloped pool and the exact one
for the volumes worlds actually have.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, Tuple

import numpy as np

from OpenGLContext.scenegraph.water.medium import WATER, worst_of

__all__ = ['Volume', 'Volumes']


@dataclass(frozen=True)
class Volume:
    """One box of a substance, in world metres."""

    minimum: Tuple[float, float, float]
    maximum: Tuple[float, float, float]
    medium: str = WATER

    def size(self) -> float:
        """How much space this box takes, for a caller choosing between two."""
        return float(np.prod([high - low for low, high
                              in zip(self.minimum, self.maximum, strict=True)]))

    def contains(self, point: Any) -> bool:
        """Whether a point is inside this box.

        The boundary counts as inside: a body exactly at the waterline is in
        the water, and the alternative is a plane one frame thick where the
        swimmer is neither in nor out.
        """
        where = np.asarray(point, dtype='d').ravel()
        return bool(all(low <= float(where[axis]) <= high
                        for axis, (low, high)
                        in enumerate(zip(self.minimum, self.maximum,
                                         strict=True))))

    @classmethod
    def below(cls, minimum: Tuple[float, float], maximum: Tuple[float, float],
              level: float, depth: float, medium: str = WATER) -> 'Volume':
        """A sheet of water over a footprint, and the ``depth`` under it.

        A lake is a level and a footprint; how far down it goes is the bed's
        business, so the caller says how deep to look. Deep enough that a body
        cannot fall through the bottom of it in one frame.
        """
        return cls(minimum=(float(minimum[0]), float(level) - float(depth),
                            float(minimum[1])),
                   maximum=(float(maximum[0]), float(level),
                            float(maximum[1])),
                   medium=medium)


class Volumes:
    """The media a world has, and what is at a point."""

    def __init__(self, volumes: Sequence[Volume] = ()) -> None:
        self.volumes = list(volumes)

    def __len__(self) -> int:
        return len(self.volumes)

    def at(self, point: Any) -> list[str]:
        """Every substance a point is inside."""
        return [volume.medium for volume in self.volumes
                if volume.contains(point)]

    def medium_at(self, point: Any, rule: str = 'worst') -> str:
        """Which substance a point is in, or ``''`` for dry air.

        Two worlds want two answers where volumes overlap, and both are right
        about their own maps:

        ``worst``
            the one that will hurt most. A body half in a pool and half in the
            lava under it needs to hear about the lava.
        ``smallest``
            the most specific. Where the boxes are some partition's own bounds
            rather than the liquid's shape -- a BSP leaf, a tile -- neighbours
            overlap at their edges, and a pit of lava inside a flooded room is
            the smaller box and the answer that matters.
        """
        if rule not in _RULES:
            raise ValueError(
                "%r is not a way of choosing between overlapping volumes; "
                "there is %s" % (rule, ' and '.join(sorted(_RULES))))
        return _RULES[rule](self, point)

    def _worst(self, point: Any) -> str:
        return worst_of(self.at(point))

    def _smallest(self, point: Any) -> str:
        inside = [volume for volume in self.volumes if volume.contains(point)]
        if not inside:
            return ''
        return min(inside, key=lambda volume: volume.size()).medium


#: How to choose between volumes a point is in. Declared rather than branched
#: on, so a world that wants a third writes one instead of editing this.
_RULES = {'worst': Volumes._worst, 'smallest': Volumes._smallest}
