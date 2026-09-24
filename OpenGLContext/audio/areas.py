"""How loud an area's sound is at the listener's position.

An area's ambience is a looping ``global`` source whose ``gain`` the
application sets each frame from the camera's position; the functions here
give that gain, fading over a margin so that walking out of an area fades its
sound rather than cutting it.  See ``docs/audio.rst``.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = ['box_gain']


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
