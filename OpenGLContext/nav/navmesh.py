"""A navigation mesh built from a collision mesh, and paths across it.

**Generated, never baked.** The engines this project reads maps from shipped
pre-computed navigation data beside their levels; we have something better
available at load time — the collision mesh itself, already in memory — so the
mesh is derived from the geometry a character actually walks on. That is not
only the licensing answer, it is the better engineering one: it gives
navigation for levels nobody ever baked, it regenerates when the geometry
changes, and it depends on no content we may not read.

The pieces, in the order a path goes through them:

=====================  =======================================================
:func:`build`          Walkable triangles, by slope, with their neighbours
                       found by shared edges.
:meth:`NavMesh.cell_at`  Which cell a point stands on.
:meth:`NavMesh.path`   A* over the cells, then **string-pulled** through the
                       portals between them.
=====================  =======================================================

The string pull matters more than it sounds. A path that followed cell centres
zigzags across an empty room — a bot walking the staircase of triangle centres
looks drunk, and every corner it rounds is one it did not need. Pulling the
line taut through the portals gives the route a person would take, and on open
floor it collapses to a straight line.

**A navmesh is built for a particular body.** The slope a character can climb
and the radius it occupies are parameters, because a mesh built for one is
wrong for another — which is why they are arguments here rather than
constants.
"""

from __future__ import annotations

import heapq
import logging
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

log = logging.getLogger(__name__)

__all__ = ['NavMesh', 'build', 'from_world']

#: Steepest surface a character is assumed to walk, in degrees.  A default
#: rather than a constant: it belongs to the body, and
#: ``CharacterCapabilities.maxSlope`` is where a game's own answer lives.
DEFAULT_MAX_SLOPE = 50.0

#: How far above a point to look for the floor it is standing on, in metres.
#: Generous enough to find the ground under a capsule's centre, short enough
#: that a point in mid-air over a pit does not bind to the bottom of it.
STAND_REACH = 2.5

#: How far a body stands above the floor, in metres, when a caller asks for the
#: headroom test.  **Off by default, and that is a known limitation rather than
#: a preference.**  The test compares bounding boxes, and a level's wall
#: triangles are large: on `oa_dm1` it removed 1092 of 1220 floor cells, almost
#: all of them nowhere near a wall.  It is right on the small, axis-aligned
#: geometry it was written against and too blunt for a real level, where what
#: is wanted is the blocker's distance from the cell rather than whether their
#: boxes touch.  Until that is written, a caller who knows their geometry is
#: simple can pass a clearance and everyone else gets the whole walkable floor.
DEFAULT_CLEARANCE = 0.0

#: How far *below* a point its floor may be and still count as the one it is
#: standing on.  Not zero: a sloped floor's plane runs above and below the
#: sample a caller took from a neighbouring triangle, and a hard zero rejects
#: the cell a body is plainly on.
STAND_TOLERANCE = 0.5

#: Below this a triangle has no meaningful normal and is dropped.
_TINY = 1e-12

Point = Tuple[float, float, float]


class NavMesh:
    """Walkable cells and the connections between them.

    A cell is one triangle of walkable floor.  Triangles rather than merged
    convex regions because a collision mesh arrives as triangles and the search
    is fast enough on them: merging is an optimisation to reach for when a
    level's cell count actually hurts, and it changes nothing about the
    interface above it.
    """

    def __init__(self, points: np.ndarray, cells: np.ndarray,
                 neighbours: Dict[int, List[int]],
                 portals: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]]
                 ) -> None:
        self.points = points
        #: ``(N, 3)`` vertex indices, one row per walkable cell.
        self.cells = cells
        #: Cell index to the cells sharing an edge with it.
        self.neighbours = neighbours
        #: The shared edge between two cells, as its two endpoints.
        self.portals = portals
        self._centres = (points[cells].mean(axis=1)
                         if len(cells) else np.zeros((0, 3)))

    def __len__(self) -> int:
        return len(self.cells)

    # -- where you are ---------------------------------------------------
    def cell_at(self, point: Sequence[float], reach: float = STAND_REACH,
                below: float = STAND_TOLERANCE) -> Optional[int]:
        """The cell ``point`` is standing on, or None.

        The cell *under* the point, within ``reach``: height is what tells two
        floors stacked over one another apart, and a point in mid-air belongs
        to neither.
        """
        if not len(self.cells):
            return None
        where = np.asarray(point, dtype='d')
        best: Optional[int] = None
        best_drop = math.inf
        for index in self._over(where):
            height = self._height_at(index, where)
            if height is None:
                continue
            drop = float(where[1]) - height
            # A little below counts: a capsule's own centre sits above the
            # floor, and on a slope the plane runs either side of a sample
            # taken from the triangle next door.
            if -below <= drop <= reach and drop < best_drop:
                best, best_drop = index, drop
        return best

    def _over(self, where: np.ndarray) -> List[int]:
        """Every cell whose footprint contains ``where`` seen from above."""
        found = []
        for index, cell in enumerate(self.cells):
            if _inside_2d(self.points[cell], where):
                found.append(index)
        return found

    def _height_at(self, index: int, where: np.ndarray) -> Optional[float]:
        """The floor height of a cell below ``where``, or None if it is outside."""
        a, b, c = self.points[self.cells[index]]
        normal = np.cross(b - a, c - a)
        if abs(float(normal[1])) < _TINY:
            return None
        return float(a[1] - ((where[0] - a[0]) * normal[0]
                             + (where[2] - a[2]) * normal[2]) / normal[1])

    def random_point(self, seed: Optional[int] = None) -> Optional[Point]:
        """Somewhere on the mesh, or None if there is nowhere.

        What a bot with nothing better to do walks toward.  Seeded, so a match
        replays from its inputs.
        """
        if not len(self.cells):
            return None
        chooser = random.Random(seed)
        index = chooser.randrange(len(self.cells))
        return _point(self._centres[index])

    # -- getting there ---------------------------------------------------
    def path(self, start: Sequence[float],
             goal: Sequence[float]) -> List[Point]:
        """A route from ``start`` to ``goal``, or an empty list.

        Empty when either end is off the mesh or nothing connects them —
        a normal answer, not an error: a bot on a ledge with no way down has
        nowhere to walk and should do something else.
        """
        first = self.cell_at(start)
        last = self.cell_at(goal)
        if first is None or last is None:
            return []
        origin = _point(start)
        target = _point(goal)
        if first == last:
            return [target] if origin != target else [origin]
        cells = self._search(first, last)
        if not cells:
            return []
        return self._pull(origin, target, cells)

    def _search(self, first: int, last: int) -> List[int]:
        """A* over the cells, by straight-line distance between their centres."""
        came: Dict[int, int] = {}
        best: Dict[int, float] = {first: 0.0}
        queue: List[Tuple[float, int]] = [(self._gap(first, last), first)]
        seen = set()
        while queue:
            _estimate, current = heapq.heappop(queue)
            if current == last:
                return _walk_back(came, first, last)
            if current in seen:
                continue
            seen.add(current)
            for neighbour in self.neighbours.get(current, ()):
                cost = best[current] + self._gap(current, neighbour)
                if cost < best.get(neighbour, math.inf):
                    best[neighbour] = cost
                    came[neighbour] = current
                    heapq.heappush(queue,
                                   (cost + self._gap(neighbour, last), neighbour))
        return []

    def _gap(self, one: int, other: int) -> float:
        return float(np.linalg.norm(self._centres[one] - self._centres[other]))

    def _pull(self, start: Point, goal: Point, cells: List[int]) -> List[Point]:
        """Pull the line taut through the portals the cells share.

        The simple stupid funnel: two edges of a cone are narrowed by each
        portal in turn, and a corner is planted whenever they cross.  Without
        it a path is a list of triangle centres, which on open floor is a
        zigzag across a room that has nothing in it.
        """
        gates = [self.portals[(cells[index], cells[index + 1])]
                 for index in range(len(cells) - 1)
                 if (cells[index], cells[index + 1]) in self.portals]
        corners: List[Point] = [start]
        apex = np.asarray(start, dtype='d')
        left = right = apex
        left_at = right_at = 0
        index = 0
        while index < len(gates) + 1:
            gate = gates[index] if index < len(gates) else (
                np.asarray(goal, dtype='d'), np.asarray(goal, dtype='d'))
            new_left, new_right = _oriented(apex, gate)
            if _area(apex, right, new_right) <= 0.0:
                if np.allclose(apex, right) or _area(apex, left, new_right) > 0.0:
                    right, right_at = new_right, index
                else:
                    corners.append(_point(left))
                    apex = left
                    index = left_at
                    left = right = apex
                    left_at = right_at = index
                    index += 1
                    continue
            if _area(apex, left, new_left) >= 0.0:
                if np.allclose(apex, left) or _area(apex, right, new_left) < 0.0:
                    left, left_at = new_left, index
                else:
                    corners.append(_point(right))
                    apex = right
                    index = right_at
                    left = right = apex
                    left_at = right_at = index
                    index += 1
                    continue
            index += 1
        corners.append(goal)
        return _tidied(corners)


def build(points: Any, triangles: Any,
          max_slope: float = DEFAULT_MAX_SLOPE,
          clearance: float = DEFAULT_CLEARANCE) -> NavMesh:
    """The walkable part of a collision mesh, with its cells joined up.

    A triangle is walkable when it faces upward, has room to stand on, and is
    no steeper than
    ``max_slope`` — the character's own limit, since a mesh built for one body
    is wrong for another.  A downward-facing triangle is a ceiling however flat
    it is, and nobody walks on one.

    The headroom test is what makes a wall an obstacle.  A wall standing on a
    floor contributes no walkable triangles of its own, but the floor either
    side of it is still floor -- and without the test the two halves are joined
    straight through it, so a bot paths through the wall because as far as the
    mesh is concerned there is nothing there.
    """
    points = np.asarray(points, dtype='d')
    triangles = np.asarray(triangles, dtype='i')
    if not len(triangles):
        return NavMesh(points, np.zeros((0, 3), dtype='i'), {}, {})
    corners = points[triangles]
    normals = np.cross(corners[:, 1] - corners[:, 0],
                       corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    usable = lengths > _TINY
    upward = np.zeros(len(triangles))
    upward[usable] = normals[usable, 1] / lengths[usable]
    walkable = usable & (upward >= math.cos(math.radians(max_slope)))
    cells = triangles[walkable]
    cells = _with_headroom(points, cells, corners[~walkable], clearance)
    neighbours, portals = _join(points, cells)
    return NavMesh(points, cells, neighbours, portals)


def from_world(world: Any, max_slope: float = DEFAULT_MAX_SLOPE,
               clearance: float = DEFAULT_CLEARANCE) -> NavMesh:
    """A navmesh over every static trimesh in a physics world.

    The seam a game uses: the collision mesh a level was loaded into is already
    the thing a character walks on, so the navmesh is built from that rather
    than from a second description of the same geometry that could disagree
    with it.
    """
    parts = []
    for body in range(world.body_count):
        index = int(world.collider_shape[body])
        if index < 0:
            continue
        shape = world.shapes[index]
        if str(shape.type) != 'trimesh' or shape.points is None:
            continue
        centre = np.asarray(world.position[body], dtype='d')
        parts.append((np.asarray(shape.points, dtype='d') + centre,
                      np.asarray(shape.indices, dtype='i')))
    if not parts:
        return NavMesh(np.zeros((0, 3)), np.zeros((0, 3), dtype='i'), {}, {})
    points, triangles, offset = [], [], 0
    for part_points, part_triangles in parts:
        points.append(part_points)
        triangles.append(part_triangles + offset)
        offset += len(part_points)
    return build(np.vstack(points), np.vstack(triangles),
                 max_slope=max_slope, clearance=clearance)


# -- joining the cells up ----------------------------------------------------

def _join(points: np.ndarray, cells: np.ndarray) -> Tuple[Dict[int, List[int]],
                                                          Dict[Tuple[int, int],
                                                               Tuple[np.ndarray,
                                                                     np.ndarray]]]:
    """Neighbours and portals, by shared edge.

    Two cells are joined when they share two vertices **by position**, not by
    index.  A collision mesh built from a level is a triangle soup: the same
    corner appears once per triangle that touches it, with a different index
    each time, so matching indices joins nothing at all and every cell is an
    island with no way off it.  Positions are welded on a grid fine enough to
    be exact for geometry authored in map units and coarse enough to survive
    the arithmetic that got them into world space.
    """
    welded = _welded(points)
    edges: Dict[Tuple[int, int], List[int]] = {}
    for index, cell in enumerate(cells):
        for first, second in ((0, 1), (1, 2), (2, 0)):
            key = _edge(int(welded[int(cell[first])]),
                        int(welded[int(cell[second])]))
            edges.setdefault(key, []).append(index)
    neighbours: Dict[int, List[int]] = {index: [] for index in range(len(cells))}
    portals: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]] = {}
    for _key, sharing in edges.items():
        if len(sharing) != 2:
            continue
        left, right = sharing
        neighbours[left].append(right)
        neighbours[right].append(left)
        gate = _shared_edge(points, cells[left], cells[right], welded)
        portals[(left, right)] = gate
        portals[(right, left)] = gate
    return (neighbours, portals)


def _with_headroom(points: np.ndarray, cells: np.ndarray,
                   blockers: np.ndarray, clearance: float) -> np.ndarray:
    """Drop the cells a body could not stand on for want of room above.

    Tested as **footprints overlapping**, not as a point inside a box: a wall
    in a level is a flat plane of zero thickness, so a point test never touches
    one and every wall would be invisible to the mesh.  Overlapping the cell's
    own box against the blocker's is what catches it — and it errs on the side
    of removing the floor immediately against a wall, which is right anyway,
    since a body has a radius and cannot stand there.
    """
    if not len(cells) or not len(blockers) or clearance <= 0.0:
        return cells
    corners = points[cells]
    cell_low, cell_high = corners.min(axis=1), corners.max(axis=1)
    low, high = blockers.min(axis=1), blockers.max(axis=1)
    keep = np.ones(len(cells), dtype=bool)
    for index in range(len(cells)):
        floor = float(cell_low[index][1])
        over = ((low[:, 0] <= cell_high[index][0])
                & (high[:, 0] >= cell_low[index][0])
                & (low[:, 2] <= cell_high[index][2])
                & (high[:, 2] >= cell_low[index][2])
                # In the column of air a body standing here would occupy.
                & (high[:, 1] > floor + _TINY)
                & (low[:, 1] < floor + clearance))
        if over.any():
            keep[index] = False
    return cells[keep]


#: How finely positions are welded when looking for shared edges, in metres.
#: A tenth of a millimetre: far below anything a level distinguishes, far above
#: the drift of transforming a mesh into world space.
WELD = 1e-4


def _point(value: Any) -> Point:
    """Anything three numbers long as a plain ``(x, y, z)``."""
    found = np.asarray(value, dtype='d')
    return (float(found[0]), float(found[1]), float(found[2]))


def _welded(points: np.ndarray) -> np.ndarray:
    """A per-vertex id that is equal wherever two vertices are in one place."""
    if not len(points):
        return np.zeros(0, dtype='i8')
    keys = np.round(np.asarray(points, dtype='d') / WELD).astype('i8')
    _unique, identity = np.unique(keys, axis=0, return_inverse=True)
    return identity.reshape(-1)


def _edge(one: int, other: int) -> Tuple[int, int]:
    return (one, other) if one < other else (other, one)


def _shared_edge(points: np.ndarray, left: np.ndarray, right: np.ndarray,
                 welded: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The two corners two cells have in common, as positions.

    Taken from the cells rather than from the edge key, because the key is a
    welded id and what the funnel needs is a place.
    """
    theirs = {int(welded[int(index)]) for index in right}
    shared = [points[int(index)] for index in left
              if int(welded[int(index)]) in theirs]
    if len(shared) >= 2:
        return (shared[0], shared[1])
    return (points[int(left[0])], points[int(left[1])])


def _walk_back(came: Dict[int, int], first: int, last: int) -> List[int]:
    route = [last]
    while route[-1] != first:
        route.append(came[route[-1]])
    route.reverse()
    return route


# -- the funnel --------------------------------------------------------------

def _area(apex: np.ndarray, one: np.ndarray, other: np.ndarray) -> float:
    """Twice the signed area of a triangle, seen from above.

    Positive when ``other`` is to the left of ``one`` about ``apex``.  Seen
    from above because a funnel is a horizontal question: a path's height
    follows the floor and is not something to be pulled taut.
    """
    return float((one[0] - apex[0]) * (other[2] - apex[2])
                 - (other[0] - apex[0]) * (one[2] - apex[2]))


def _oriented(apex: np.ndarray,
              gate: Tuple[np.ndarray, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """A portal's endpoints as (left, right) seen from ``apex``."""
    one, other = gate
    if _area(apex, one, other) < 0.0:
        return (other, one)
    return (one, other)


def _tidied(corners: List[Point]) -> List[Point]:
    """Drop the corners that repeat, which a funnel plants at its own apex."""
    kept: List[Point] = []
    for corner in corners:
        if not kept or not np.allclose(kept[-1], corner, atol=1e-9):
            kept.append(corner)
    return kept


def _inside_2d(corners: np.ndarray, where: np.ndarray) -> bool:
    """Whether ``where`` is inside a triangle, seen from above."""
    a, b, c = corners
    first = _area(a, b, where)
    second = _area(b, c, where)
    third = _area(c, a, where)
    return (first >= -1e-9 and second >= -1e-9 and third >= -1e-9) or \
           (first <= 1e-9 and second <= 1e-9 and third <= 1e-9)
