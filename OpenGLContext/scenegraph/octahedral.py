"""Folding the directions you can look at something from onto a square.

An impostor replaces a model with a picture of it, and which picture is right
depends on where it is being looked at from. One picture per direction is a
*sphere* of pictures, and a sphere does not fit in a texture; the octahedral map
is how it is made to. Inflate an octahedron to the sphere, cut it along its
equator and unfold it flat, and every direction has a place on a unit square --
with directions near each other in space landing near each other on it, which is
what lets four neighbouring pictures be blended into the view actually wanted.

Two layouts, and a chain says which it used:

**hemi** (the default)
    The upper hemisphere only, spending the whole square on it. What a thing
    standing on the ground wants: nobody walks under a bust, and a sphere's
    lower half would be half the resolution spent on views nobody takes.
    ``+Y`` is up, which is the axis glTF and this engine agree on.

**full**
    The whole sphere, the lower half folded into the corners. For something
    seen from any side -- a rock, an asteroid, a thing in flight.

Nothing here touches GL. The shader samples this mapping and the baker renders
against it, and they are only the same impostor if they are the same
arithmetic, so the arithmetic is in one place and is tested on its own.

Reference:
    Cigolle et al., *A Survey of Efficient Representations for Independent Unit
    Vectors*, JCGT 3(2), 2014 -- the octahedral mapping and its inverse.
"""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

__all__ = [
    'MINIMUM_TILE',
    'cell_of',
    'direction_to_uv',
    'tile_origin',
    'tile_size',
    'uv_to_direction',
    'view_directions',
]

#: The fewest pixels a view may be across. Below this an impostor is not a
#: picture of the model, it is a smudge the colour of it.
MINIMUM_TILE = 8

_TINY = 1e-12


def direction_to_uv(direction: Sequence[float],
                    hemi: bool = True) -> Tuple[float, float]:
    """Where on the unit square a direction's picture lives.

    ``direction`` need not be normalised. In the hemi layout a direction below
    the horizon is folded up onto it, because that is the nearest view the
    atlas holds rather than an error: a model on the ground seen from slightly
    below is seen against its own horizon.
    """
    vector = np.asarray(direction, dtype='d')
    length = float(np.linalg.norm(vector))
    if length < _TINY:
        return 0.5, 0.5
    x, y, z = vector / length
    if hemi:
        y = abs(y)
    scale = abs(x) + abs(y) + abs(z)
    x, y, z = x / scale, y / scale, z / scale
    if hemi:
        u, v = x + z, z - x
    elif y >= 0.0:
        u, v = x, z
    else:
        # The lower half folds outward into the corners.
        u = (1.0 - abs(z)) * (1.0 if x >= 0.0 else -1.0)
        v = (1.0 - abs(x)) * (1.0 if z >= 0.0 else -1.0)
    return _clamped(u * 0.5 + 0.5), _clamped(v * 0.5 + 0.5)


def uv_to_direction(uv: Sequence[float],
                    hemi: bool = True) -> Tuple[float, float, float]:
    """The direction whose picture lives at ``uv``; the inverse of the above."""
    u = float(uv[0]) * 2.0 - 1.0
    v = float(uv[1]) * 2.0 - 1.0
    if hemi:
        x, z = (u - v) * 0.5, (u + v) * 0.5
        y = 1.0 - abs(x) - abs(z)
    else:
        x, z = u, v
        y = 1.0 - abs(x) - abs(z)
        if y < 0.0:
            x, z = ((1.0 - abs(z)) * (1.0 if x >= 0.0 else -1.0),
                    (1.0 - abs(x)) * (1.0 if z >= 0.0 else -1.0))
    found = np.array([x, y, z], dtype='d')
    length = float(np.linalg.norm(found))
    if length < _TINY:
        return 0.0, 1.0, 0.0
    found = found / length
    return float(found[0]), float(found[1]), float(found[2])


def view_directions(grid: int, hemi: bool = True) -> list:
    """The ``grid`` x ``grid`` directions an atlas holds pictures from.

    One per cell and taken at its **centre**, so a view is the middle of the
    square it fills. Taken at the corner instead, two neighbouring cells would
    hold the same view and the blend between them would say nothing.

    Row-major, matching the order the tiles are laid out in the image.
    """
    _refuse_grid(grid)
    step = 1.0 / grid
    return [uv_to_direction(((column + 0.5) * step, (row + 0.5) * step), hemi)
            for row in range(grid) for column in range(grid)]


def cell_of(direction: Sequence[float], grid: int,
            hemi: bool = True) -> Tuple[int, int]:
    """Which cell of a ``grid`` x ``grid`` atlas a direction falls in."""
    _refuse_grid(grid)
    u, v = direction_to_uv(direction, hemi)
    column = min(grid - 1, max(0, int(u * grid)))
    row = min(grid - 1, max(0, int(v * grid)))
    return row, column


def tile_size(image: int, grid: int) -> int:
    """How many pixels across one view is, in a square atlas of ``image``."""
    _refuse_grid(grid)
    if image % grid:
        raise ValueError(
            'an atlas of %d pixels does not divide into %d views a side; a '
            'view would straddle a pixel' % (image, grid))
    size = image // grid
    if size < MINIMUM_TILE:
        raise ValueError(
            '%d views a side of a %d-pixel atlas is %d pixels a view, which '
            'is not a picture of anything' % (grid, image, size))
    return size


def tile_origin(row: int, column: int, image: int, grid: int) -> Tuple[int, int]:
    """The top-left pixel of one view's tile, as ``(x, y)``."""
    size = tile_size(image, grid)
    return column * size, row * size


def _clamped(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def _refuse_grid(grid: int) -> None:
    if grid < 1:
        raise ValueError('an atlas holds at least one view')
