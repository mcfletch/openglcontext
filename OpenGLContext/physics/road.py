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

from OpenGLContext.scenegraph.road import (
    RoadProfile, banked_sections, road_surface, widened_sections,
)
from OpenGLContext.scenegraph.roadworks import BarrierProfile, barrier_wall

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
    :param bank: how far the road leans at each centreline point, as a fraction
        and signed the way
        :func:`~OpenGLContext.scenegraph.road.plan_curvature` is. A world that
        banks its corners writes this beside its centreline, and a collider
        swept without it is a flat road under a leaning one -- which is a car
        driving through the carriageway on the inside of every corner.
    :param widening: how much more carriageway the road has at each centreline
        point, in metres. A stretch built to be passed on is wider than the road
        it is on, and a collider swept at the road's nominal width is a wall
        down each edge of the extra tarmac.
    :param barriers: the stretches that are **carried** -- a deck, a causeway --
        as ``(from, to)`` distances along the centreline in metres. Each gets a
        wall along both edges, because beside a deck there is nothing but the
        thing the bridge was built over. The drawn structure has a barrier there
        for exactly this reason; one that is not collided with keeps nothing on
        anything, and the car goes through the railing and off the edge.

        Which stretches those are is the caller's to say: a bore is carried too
        and wants no wall, since what is beside it is the hillside it is in.
    :param barrier: what those walls are, or None for an ordinary one.
    """

    def __init__(self, world: "PhysicsWorld", points: Any,
                 profile: Optional[RoadProfile] = None,
                 reach: float = REACH_METRES, chunk: float = CHUNK_METRES,
                 closed: bool = False, bank: Any = None,
                 widening: Any = None, barriers: Any = (),
                 barrier: Optional[BarrierProfile] = None) -> None:
        self.world = world
        self.points = np.asarray(points, dtype='d').reshape(-1, 3)
        if len(self.points) < 2:
            raise ValueError("a road needs a centreline of at least two points")
        self.profile = profile or RoadProfile()
        #: The lean at each point, or None for a road that does not bank.
        self.bank: Optional[np.ndarray] = self._along(bank, 'leans')
        #: How much wider the carriageway is at each point, or None for a road
        #: of one width.
        self.widening: Optional[np.ndarray] = self._along(widening,
                                                          'widenings')
        #: The stretches with an edge to fall off, as ``(from, to)`` metres.
        self.barriers = tuple((float(low), float(high))
                              for low, high in (barriers or ()))
        self.barrier = barrier or BarrierProfile()
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
        self._bodies: dict[int, list] = {}
        self._counts: dict[int, int] = {}
        self._triangles = 0

    def _along(self, values: Any, what: str) -> Optional[np.ndarray]:
        """One figure per centreline point, or None for a road that has none."""
        if values is None:
            return None
        found = np.asarray(values, dtype='d').reshape(-1)
        if len(found) != len(self.points):
            raise ValueError("a road of %d points needs %d %s, not %d"
                             % (len(self.points), len(self.points), what,
                                len(found)))
        return found

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
        lean = self._span_of(self.bank, first, last, key)
        wider = self._span_of(self.widening, first, last, key)
        if self.closed and key == self._chunks - 1:
            # Close the loop: the last chunk runs on into the first point.
            run = np.vstack([run, self.points[:1]])
        positions, _normals, _uv, indices = road_surface(
            run, self.profile, sections=self._sections(len(run), lean, wider),
            bank=lean)
        pieces = [(np.asarray(positions, dtype='d'),
                   np.asarray(indices, dtype='i').reshape(-1, 3))]
        pieces.extend(self._walls(first, last, key, lean))
        bodies = []
        for points, triangles in pieces:
            shape = self.world.add_shape(model.Shape.trimesh(points, triangles))
            bodies.append(self.world.add_body(
                model.Motion(type=model.STATIC),
                collider=model.Collider(shape=shape)))
            self._triangles += len(triangles)
        self._bodies[key] = bodies
        self._counts[key] = sum(len(triangles) for _points, triangles in pieces)
        self.world.refit_aabbs()

    def _walls(self, first: int, last: int, key: int,
               lean: Optional[np.ndarray]) -> list:
        """The barrier along each carried stretch this chunk covers.

        One wall per stretch rather than one for the chunk: a chunk may hold the
        end of a deck and the road after it, and a wall run on past the abutment
        is a wall down the middle of an ordinary road.
        """
        out = []
        for low, high in self.barriers:
            begin = max(int(np.searchsorted(self.stations, low)) - 1, first)
            end = min(int(np.searchsorted(self.stations, high)), last)
            if end - begin < 1:
                continue
            run = self.points[begin:end + 1]
            over = None if lean is None else self.bank[begin:end + 1]
            wall = barrier_wall(run, self.profile, self.barrier, bank=over)
            out.append((np.asarray(wall.positions, dtype='d'),
                        np.asarray(wall.indices, dtype='i').reshape(-1, 3)))
        return out

    def _span_of(self, values: Optional[np.ndarray], first: int, last: int,
                 key: int) -> Optional[np.ndarray]:
        """One chunk's worth of a per-point figure, closing the loop if it ends."""
        if values is None:
            return None
        found = values[first:last + 1]
        if self.closed and key == self._chunks - 1:
            found = np.concatenate([found, values[:1]])
        return found

    def _sections(self, rings: int, lean: Optional[np.ndarray],
                  wider: Optional[np.ndarray]) -> Any:
        """The cut across each ring of a chunk, or None where it never changes.

        The road is widened and then the camber taken out of it by the lean,
        exactly as in the surface that is drawn
        (:func:`~OpenGLContext.scenegraph.road.widened_sections`,
        :func:`~OpenGLContext.scenegraph.road.banked_sections`). Two centimetres
        of crown is nothing to look at and everything to a car: left in, the
        collider stands proud of the drawn road down the middle of every banked
        corner.
        """
        if lean is None and wider is None:
            return None
        found = np.tile(self.profile.section(), (rings, 1, 1))
        if wider is not None:
            found = widened_sections(found, wider, self.profile)
        if lean is not None:
            found = banked_sections(found, lean, self.profile)
        return found

    def _drop(self, key: int) -> None:
        remove = getattr(self.world, 'remove_body', None)
        for body in self._bodies.pop(key):
            if remove is not None:
                remove(body)
        # What is held, not what has ever been built: a count that only went up
        # says a lap of driving is carrying the whole world's road.
        self._triangles -= self._counts.pop(key, 0)
