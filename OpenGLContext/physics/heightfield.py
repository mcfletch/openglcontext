"""Ground to stand on, when the ground is a height field rather than tiles.

A world small enough to hold one
:class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain` has no streamed
tiles for
:class:`~OpenGLContext.loaders.tiles3d.physics_colliders.TerrainColliders` to
turn into colliders, so the field provides them itself.

The field is cut into square chunks and only the ones near the focus are
bodies of the physics service. A four-kilometre field at two-metre spacing is
half a million triangles; a car touches four of them at a time, and the
collision broadphase pays for every one it is holding. What is out of reach is
removed again, so an hour of driving costs what one view of the world costs.

:class:`HeightFieldColliders` is a collider source
(:mod:`OpenGLContext.physics.sources`)::

    ground = HeightFieldColliders(field, holes=bores)
    physics.add_collider_source(ground, focus=lambda: car.position)

Chunks are cut on the field's own grid lines and share their edge rows, so two
neighbours agree exactly where they meet -- a seam between them is a hole a
wheel falls through.

A field is a *surface*, and something passing through the ground rather than
over it -- a tunnel's bore -- has no way to say so in one. So a caller says
where the ground is not there, with ``holes``: the collider is cut wherever that
is set, while the surface a player sees keeps the hill it runs inside.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.sources import Addition, Changes

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

__all__ = ['HeightFieldColliders', 'CHUNK_METRES', 'REACH_METRES']

#: How big a chunk of ground is, in metres. Small enough that what is loaded is
#: mostly what is near, large enough that a lap does not spend its time
#: rebuilding triangle indexes.
CHUNK_METRES = 128.0

#: How far from the focus ground is kept, in metres. Past this a wheel is not
#: going to reach it before the next update does.
REACH_METRES = 320.0


class HeightFieldColliders:
    """Static trimesh colliders for the chunks of a height field near the focus.

    A :class:`~OpenGLContext.physics.sources.ColliderSource`: each chunk within
    ``reach`` of the focus is a static body of the service the source is added
    to, keyed ``(i, j)`` on the chunk grid.

    :param field: the ground.
    :param reach: how far from the focus ground is kept, in metres.
    :param chunk: how big one chunk is, in metres; rounded to whole cells of
        the field's grid, and never smaller than one cell.
    :param holes: ``holes(x, z) -> mask`` over arrays of world positions, true
        where the ground is not to be collided against -- over a tunnel's bore,
        say. A triangle is dropped when its centre is in a hole, so the opening
        is the mask to within half a cell: cutting by any corner instead widens
        it by a whole cell, and a hole wider than the bore it was cut for is a
        trench beside the road. A chunk with nothing left of it makes no body.
    """

    def __init__(self, field: HeightField,
                 reach: float = REACH_METRES,
                 chunk: float = CHUNK_METRES,
                 holes: Callable[[Any, Any], Any] | None = None) -> None:
        self.field = field
        self.reach = float(reach)
        self.holes = holes
        cell = field.extent / max(field.res - 1, 1)
        #: Cells per chunk, so a chunk's edges fall on the field's own grid.
        self.cells = max(int(round(float(chunk) / cell)), 1)
        self.chunk = self.cells * cell
        self._across = int(np.ceil((field.res - 1) / self.cells))
        #: The triangles of each chunk held, by key; zero for a chunk cut away
        #: entirely, which has no body and is not cut again while it is held.
        self._held: dict[tuple[int, int], int] = {}
        self._triangles = 0

    def update(self, focus: Sequence[float]) -> Changes:
        """The chunks to add and to drop now that the focus is at ``focus``."""
        wanted = set(self._within(focus))
        removed: list[tuple[int, int]] = []
        for key in list(self._held):
            if key not in wanted:
                count = self._held.pop(key)
                self._triangles -= count
                if count:
                    removed.append(key)
        added: list[Addition] = []
        for key in wanted:
            if key not in self._held:
                points, indices = self._patch(*key)
                self._held[key] = len(indices)
                self._triangles += len(indices)
                if len(indices):
                    added.append(Addition(key, Proxy.trimesh(points, indices), (0.0, 0.0, 0.0)))
        return Changes(add=added, remove=removed)

    def clear(self) -> None:
        """Forget every chunk, so the next update adds what is within reach afresh."""
        self._held.clear()
        self._triangles = 0

    def chunk_count(self) -> int:
        """How many chunks of ground are bodies now."""
        return sum(1 for count in self._held.values() if count)

    def triangle_count(self) -> int:
        """How many triangles those chunks are made of."""
        return self._triangles

    def _within(self, position: Sequence[float]) -> list[tuple[int, int]]:
        """Which chunks come within reach of a point, in plan."""
        at = np.asarray(position, dtype='d').reshape(-1)
        half = self.field.extent / 2.0
        # Chunk (i, j) spans cells [i*cells, (i+1)*cells] of the grid, which is
        # the world square starting `half` back from the field's west edge.
        low = np.arange(self._across) * self.chunk - half
        high = np.minimum(low + self.chunk, half)
        # Distance from the point to the chunk's box, per axis, then combined.
        dx = np.maximum(np.maximum(low - at[0], at[0] - high), 0.0)
        dz = np.maximum(np.maximum(low - at[2], at[2] - high), 0.0)
        near_x = np.nonzero(dx <= self.reach)[0]
        near_z = np.nonzero(dz <= self.reach)[0]
        return [(int(i), int(j)) for i in near_x for j in near_z
                if float(np.hypot(dx[i], dz[j])) <= self.reach]

    def _patch(self, i: int, j: int) -> tuple[np.ndarray, np.ndarray]:
        """One chunk's vertices and triangles, cut from the field's grid.

        The chunk reaches one row past its last cell, into its neighbour's
        first, so the two share that row of vertices exactly.
        """
        field = self.field
        res = field.res
        first_x, first_z = i * self.cells, j * self.cells
        last_x = min(first_x + self.cells, res - 1)
        last_z = min(first_z + self.cells, res - 1)
        wide, deep = last_x - first_x + 1, last_z - first_z + 1
        half = field.extent / 2.0
        step = field.extent / max(res - 1, 1)
        x = -half + (first_x + np.arange(wide)) * step
        z = -half + (first_z + np.arange(deep)) * step
        gx, gz = np.meshgrid(x, z, indexing='ij')
        y = field.grid[first_z:last_z + 1, first_x:last_x + 1].T \
            * field.relief + field.base
        points = np.stack([gx.ravel(), y.ravel(), gz.ravel()], axis=-1)

        a = (np.arange(wide - 1)[:, None] * deep
             + np.arange(deep - 1)[None, :]).ravel()
        b, c = a + 1, a + deep
        d = c + 1
        indices = np.stack([a, b, c, b, d, c], axis=-1).reshape(-1, 3)
        if self.holes is not None:
            from OpenGLContext.scenegraph.terrain.holes import cut
            points, indices = cut(points, indices, self.holes)
        return points, indices.astype('i')
