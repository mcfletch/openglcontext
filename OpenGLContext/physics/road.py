"""The carriageway as a collider, built from the road rather than from tiles.

Tile geometry is level-of-detail geometry: the same road at whatever resolution
the streamer picked for the distance it is at, and that resolution changes as a
car drives. Two resolutions of one curve are the better part of a metre apart,
so the surface under the wheels *steps* every time the streamer refines -- which
at racing speed is indistinguishable from hitting a wall in the middle of an
open road.

A road is a centreline and a cross-section, and a game that streams one already
has both: they travel in the tileset's ``extras``
(``OpenGLContext_editor.world.road.RoadLayer``). Built from those, the collider
is one surface at one resolution, everywhere and always, however the drawn
geometry comes and goes.

Like :class:`~OpenGLContext.physics.heightfield.HeightFieldColliders`, the road
is cut into chunks and only the ones near whatever is moving are in the physics
world -- an hour of driving costs what one view of the world costs. Chunks share
their end rings, so two neighbours agree exactly where they meet.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from omi_physics import model

from OpenGLContext.scenegraph.road import RoadProfile, road_surface

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

__all__ = ['RoadColliders', 'CHUNK_METRES', 'REACH_METRES']

#: How long a chunk of road is, in metres. Short enough that what is loaded is
#: mostly what is near, long enough that a lap does not spend its time building
#: triangle indexes.
CHUNK_METRES = 120.0

#: How far along the road, in metres, colliders are kept either side of the
#: point given. A car doing fifty metres a second wants more than a second's
#: worth in front of it.
REACH_METRES = 260.0


class RoadColliders:
    """Static trimesh colliders for the stretches of a road near a point.

    :param world: the physics world the chunks are added to and removed from.
    :param points: the centreline, (N,3) at the height the surface runs at.
    :param profile: the cross-section swept along it.
    :param reach: how far along the road, in metres, is kept either side.
    :param chunk: how long one chunk is, in metres; rounded to whole centreline
        points, and never shorter than one.
    :param closed: whether the road returns to where it started, so the chunk
        after the last is the first.
    """

    def __init__(self, world: "PhysicsWorld", points: Any,
                 profile: Optional[RoadProfile] = None,
                 reach: float = REACH_METRES, chunk: float = CHUNK_METRES,
                 closed: bool = False) -> None:
        self.world = world
        self.points = np.asarray(points, dtype='d').reshape(-1, 3)
        if len(self.points) < 2:
            raise ValueError("a road needs a centreline of at least two points")
        self.profile = profile or RoadProfile()
        self.reach = float(reach)
        self.closed = bool(closed)
        steps = np.linalg.norm(np.diff(self.points, axis=0), axis=1)
        #: Distance along the road to each point, which is what a chunk is cut
        #: on and what a position is found in.
        self.stations = np.concatenate([[0.0], np.cumsum(steps)])
        spacing = float(np.median(steps)) if len(steps) else 1.0
        #: Centreline points per chunk, so a chunk's ends fall on the road's own
        #: rings and two neighbours share the ring between them.
        self.rings = max(int(round(float(chunk) / max(spacing, 1e-6))), 1)
        self._chunks = int(np.ceil((len(self.points) - 1) / self.rings)) or 1
        self._bodies: dict[int, int] = {}
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
        """How many stretches of road the physics world is holding."""
        return len(self._bodies)

    def triangle_count(self) -> int:
        """How many triangles those stretches are made of."""
        return self._triangles

    def station_of(self, position: Any) -> float:
        """How far along the road the nearest point to ``position`` is.

        Nearest in plan, so a car in the air over the road is still somewhere
        on it.
        """
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        gaps = np.hypot(self.points[:, 0] - at[0], self.points[:, 2] - at[2])
        return float(self.stations[int(gaps.argmin())])

    def _within(self, position: Any) -> list[int]:
        """Which chunks come within reach of a point, measured along the road."""
        here = self.station_of(position)
        length = float(self.stations[-1])
        found = []
        for index in range(self._chunks):
            first, last = self._span(index)
            low, high = self.stations[first], self.stations[last]
            gap = max(low - here, here - high, 0.0)
            if self.closed:
                # Round the other way as well: the chunk before the start is
                # the one at the end.
                gap = min(gap, max(low - (here + length),
                                   (here + length) - high, 0.0),
                          max((low + length) - here, here - (high + length),
                              0.0))
            if gap <= self.reach:
                found.append(index)
        return found

    def _span(self, index: int) -> tuple[int, int]:
        """The first and last centreline point of a chunk, inclusive.

        The last is the next chunk's first, so the two share that ring and the
        surface is continuous across the join.
        """
        first = index * self.rings
        return first, min(first + self.rings, len(self.points) - 1)

    def _add(self, key: int) -> None:
        first, last = self._span(key)
        if last - first < 1:                     # pragma: no cover - degenerate
            return
        run = self.points[first:last + 1]
        if self.closed and key == self._chunks - 1:
            # Close the loop: the last chunk runs on into the first point.
            run = np.vstack([run, self.points[:1]])
        positions, _normals, _uv, indices = road_surface(run, self.profile)
        shape = self.world.add_shape(model.Shape.trimesh(
            np.asarray(positions, dtype='d'),
            np.asarray(indices, dtype='i').reshape(-1, 3)))
        self._bodies[key] = self.world.add_body(
            model.Motion(type=model.STATIC),
            collider=model.Collider(shape=shape))
        self._triangles += len(indices) // 3
        self.world.refit_aabbs()

    def _drop(self, key: int) -> None:
        body = self._bodies.pop(key)
        remove = getattr(self.world, 'remove_body', None)
        if remove is not None:
            remove(body)
