"""Ground to stand on, when the ground is a height field rather than tiles.

A world small enough to hold one
:class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain` has no streamed
tiles for
:class:`~OpenGLContext.loaders.tiles3d.physics_colliders.TerrainColliders` to
turn into colliders, so the field provides them itself.

The field is cut into square chunks and only the ones near whatever is moving
are in the physics world. A four-kilometre field at two-metre spacing is half a
million triangles; a car touches four of them at a time, and the collision
broadphase pays for every one it is holding. What is out of reach is removed
again, so an hour of driving costs what one view of the world costs.

Chunks are cut on the field's own grid lines and share their edge rows, so two
neighbours agree exactly where they meet -- a seam between them is a hole a
wheel falls through.

A field is a *surface*, and something passing through the ground rather than
over it -- a tunnel's bore -- has no way to say so in one. So a caller says
where the ground is not there, with ``holes``: the collider is cut wherever that
is set, while the surface a player sees keeps the hill it runs inside.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

import numpy as np
from omi_physics import model

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

__all__ = ['HeightFieldColliders', 'CHUNK_METRES', 'REACH_METRES']

#: How big a chunk of ground is, in metres. Small enough that what is loaded is
#: mostly what is near, large enough that a lap does not spend its time
#: rebuilding triangle indexes.
CHUNK_METRES = 128.0

#: How far from the camera ground is kept, in metres. Past this a wheel is not
#: going to reach it before the next update does.
REACH_METRES = 320.0


class HeightFieldColliders:
    """Static trimesh colliders for the chunks of a height field near a point.

    :param world: the physics world the chunks are added to and removed from.
    :param field: the ground.
    :param reach: how far from the point ground is kept, in metres.
    :param chunk: how big one chunk is, in metres; rounded to whole cells of
        the field's grid, and never smaller than one cell.
    :param holes: ``holes(x, z) -> mask`` over arrays of world positions, true
        where the ground is not to be collided against -- over a tunnel's bore,
        say. A triangle is dropped when its centre is in a hole, so the opening
        is the mask to within half a cell: cutting by any corner instead widens
        it by a whole cell, and a hole wider than the bore it was cut for is a
        trench beside the road.
    """

    def __init__(self, world: "PhysicsWorld", field: "HeightField",
                 reach: float = REACH_METRES,
                 chunk: float = CHUNK_METRES,
                 holes: "Optional[Callable[[Any, Any], Any]]" = None) -> None:
        self.world = world
        self.field = field
        self.reach = float(reach)
        self.holes = holes
        cell = field.extent / max(field.res - 1, 1)
        #: Cells per chunk, so a chunk's edges fall on the field's own grid.
        self.cells = max(int(round(float(chunk) / cell)), 1)
        self.chunk = self.cells * cell
        self._across = int(np.ceil((field.res - 1) / self.cells))
        self._bodies: dict[tuple[int, int], int] = {}
        self._triangles = 0

    def update(self, position: Any) -> None:
        """Hold the chunks within reach of ``position``, and no others."""
        wanted = set(self._within(position))
        for key in list(self._bodies):
            if key not in wanted:
                self._drop(key)
        for key in wanted:
            if key not in self._bodies:
                self._add(key)

    def clear(self) -> None:
        """Let go of every chunk."""
        for key in list(self._bodies):
            self._drop(key)

    def chunk_count(self) -> int:
        """How many chunks of ground the physics world is holding."""
        return len(self._bodies)

    def triangle_count(self) -> int:
        """How many triangles those chunks are made of."""
        return self._triangles

    def _within(self, position: Any) -> list[tuple[int, int]]:
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

    def _add(self, key: tuple[int, int]) -> None:
        points, indices = self._patch(*key)
        if not len(indices):
            return
        shape = self.world.add_shape(model.Shape.trimesh(points, indices))
        self._bodies[key] = self.world.add_body(
            model.Motion(type=model.STATIC),
            collider=model.Collider(shape=shape))
        self._triangles += len(indices)
        self.world.refit_aabbs()

    def _drop(self, key: tuple[int, int]) -> None:
        body = self._bodies.pop(key)
        remove = getattr(self.world, 'remove_body', None)
        if remove is not None:
            remove(body)

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
            centre = points[indices].mean(axis=1)
            missing = np.asarray(self.holes(centre[:, 0], centre[:, 2]), bool)
            indices = indices[~missing]
        return points, indices.astype('i')
