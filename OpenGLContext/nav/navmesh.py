"""A navigation mesh built from a collision mesh, and paths across it.

**Generated, never baked.** The engines this project reads maps from shipped
pre-computed navigation data beside their levels; we have something better
available at load time — the collision mesh itself, already in memory — so the
mesh is derived from the geometry a character actually walks on. That is not
only the licensing answer, it is the better engineering one: it gives
navigation for levels nobody ever baked, it regenerates when the geometry
changes, and it depends on no content we may not read.

The pieces, in the order a path goes through them:

=======================  =====================================================
:func:`build`            Walkable triangles, by slope, with their neighbours
                         found by shared edges.
:meth:`NavMesh.cell_at`  Which cell a point stands on.
:meth:`NavMesh.corridor` A* over the cells for the run of them a route
                         crosses.
:meth:`NavMesh.visible`  Whether the line between two points stays on the
                         mesh.
:meth:`NavMesh.path`     A corridor, **string-pulled** through the portals
                         between its cells, and freed of the corners the
                         corridor rather than the geometry put there.
=======================  =====================================================

The string pull matters more than it sounds. A path that followed cell centres
zigzags across an empty room — a bot walking the staircase of triangle centres
looks drunk, and every corner it rounds is one it did not need. Pulling the
line taut through the portals gives the route a person would take, and on open
floor it collapses to a straight line.

**The funnel is taut inside its corridor and no further**, so which cells the
search picked is part of the answer rather than a detail beneath it. Between
any two cells there are many equally short runs of cells — a staircase over a
grid of triangles costs the same by its two sides as by its diagonal — and a
corridor settled by whichever of them the queue reached first is a route that
crosses a room to a wall and follows it along. Two things keep the line
straight: the search costs a step by how far a walker has to go to reach the
portal it leaves by, which prefers the diagonal, and the pulled line then drops
every corner the mesh lets it see past.

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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext import entropy

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

#: How far outside a triangle still counts as on it, in metres.  A portal
#: endpoint is a corner of both cells that share it, and a route's corners are
#: portal endpoints, so "just outside by a rounding error" is the common case
#: rather than the odd one.
_INSIDE = 1e-9

Point = Tuple[float, float, float]

#: Anything three numbers long: a :data:`Point`, or a row of an array of them.
#: The mesh keeps its geometry in arrays and does its arithmetic in floats, so
#: both turn up wherever a place is wanted.
Spot = Union[Point, np.ndarray]

#: A cell **and the cell it was entered from**, which is what the search walks
#: over: where a walker stands on arriving is what the next step is measured
#: from, and that is a property of the portal rather than of the cell.  The
#: starting cell is entered from ``-1``.
State = Tuple[int, int]


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
                 portals: Dict[Tuple[int, int], Tuple[Point, Point]]
                 ) -> None:
        self.points = points
        #: ``(N, 3)`` vertex indices, one row per walkable cell.
        self.cells = cells
        #: Cell index to the cells sharing an edge with it.
        self.neighbours = neighbours
        #: The shared edge between two cells, as its two endpoints in the
        #: order a walker crossing from the first into the second meets them:
        #: left first.  Both directions are held, each in its own order.
        self.portals = portals
        self._corners = (points[cells] if len(cells)
                         else np.zeros((0, 3, 3)))
        #: Where each cell's middle is, ``(N, 3)``: what a route over cell
        #: centres is drawn from, and where :meth:`random_point` lands.
        self.centres = self._corners.mean(axis=1)
        self._normals = np.cross(self._corners[:, 1] - self._corners[:, 0],
                                 self._corners[:, 2] - self._corners[:, 0])
        # The footprint of each cell, so a point can be matched against the
        # handful of cells it could possibly be on rather than against all of
        # them: a level's cells are counted in thousands and `cell_at` is
        # asked once per corner of every route.
        self._low = self._corners.min(axis=1)
        self._high = self._corners.max(axis=1)

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
        where = _point(point)
        best: Optional[int] = None
        best_drop = math.inf
        for index in self._footprints(where):
            drop = self._stands_on(int(index), where, reach, below)
            if drop is not None and drop < best_drop:
                best, best_drop = int(index), drop
        return best

    def _footprints(self, where: Spot) -> np.ndarray:
        """The cells whose footprint box ``where`` falls in, seen from above.

        A box holds more than the triangle inside it, so this narrows rather
        than answers; :meth:`_stands_on` decides.
        """
        return np.flatnonzero(
            (self._low[:, 0] - _INSIDE <= where[0])
            & (where[0] <= self._high[:, 0] + _INSIDE)
            & (self._low[:, 2] - _INSIDE <= where[2])
            & (where[2] <= self._high[:, 2] + _INSIDE))

    def _stands_on(self, index: int, where: Spot, reach: float,
                   below: float) -> Optional[float]:
        """How far ``where`` is above cell ``index``, or None if it is not.

        A little below counts: a capsule's own centre sits above the floor,
        and on a slope the plane runs either side of a sample taken from the
        triangle next door.
        """
        if not _inside_2d(self._corners[index], where):
            return None
        height = self._height_at(index, where)
        if height is None:
            return None
        drop = float(where[1]) - height
        return drop if -below <= drop <= reach else None

    def _height_at(self, index: int, where: Spot) -> Optional[float]:
        """The floor height of a cell below ``where``, or None if it is flat on."""
        a = self._corners[index][0]
        normal = self._normals[index]
        if abs(normal[1]) < _TINY:
            return None
        return float(a[1] - ((where[0] - a[0]) * normal[0]
                             + (where[2] - a[2]) * normal[2]) / normal[1])

    def random_point(self, seed: Optional[int] = None) -> Optional[Point]:
        """Somewhere on the mesh, or None if there is nowhere.

        What a bot with nothing better to do walks toward.  Seeded, so a match
        replays from its inputs: ``seed`` pins one answer, and without one the
        session's own navigation stream is drawn from, which advances -- a bot
        asking again wants somewhere else to go.  See
        :mod:`OpenGLContext.entropy`.
        """
        if not len(self.cells):
            return None
        chooser = (random.Random(seed) if seed is not None
                   else entropy.randomizer('navmesh'))
        index = chooser.randrange(len(self.cells))
        return _point(self.centres[index])

    # -- what you can see ------------------------------------------------
    def visible(self, start: Sequence[float], goal: Sequence[float],
                reach: float = STAND_REACH,
                below: float = STAND_TOLERANCE) -> bool:
        """Whether a body could walk straight from ``start`` to ``goal``.

        True when an unbroken run of cells covers the line between them, so a
        wall, a pit and the edge of the floor all stop it and a ramp does not.
        The run is walked over the mesh rather than measured in the plane,
        which is what keeps one storey's answer off another's: a line drawn
        over a floor below is not a line along it.

        What a bot asks before it pays for a whole path, and what
        :meth:`path` asks to drop a corner nothing is standing behind.
        """
        first = self.cell_at(start, reach=reach, below=below)
        if first is None:
            return False
        return self._reaches(first, _point(start), _point(goal), reach, below)

    def _reaches(self, first: int, origin: Point, target: Point,
                 reach: float, below: float) -> bool:
        """Whether cells lead from ``first`` along the line to ``target``.

        Depth-first over the ways the line can carry on, because a line that
        runs exactly through a shared corner leaves a cell by two edges at
        once and either of them may be the one that carries it.
        """
        stack = [first]
        seen = set()
        while stack:
            cell = stack.pop()
            if cell in seen:
                continue
            seen.add(cell)
            if self._stands_on(cell, target, reach, below) is not None:
                return True
            stack.extend(self._onward(cell, origin, target))
        return False

    def _onward(self, index: int, origin: Point,
                target: Point) -> List[int]:
        """The cells the line from ``origin`` to ``target`` leads on into.

        A portal carries the line when ``target`` lies beyond it and the line
        passes between its two ends.  A cell is convex, so the portal the line
        arrived by fails the first test and the one it leaves by is the only
        other it can pass — except through a corner, where the two portals
        meeting there both answer and the caller tries both.
        """
        found = []
        for neighbour in self.neighbours.get(index, ()):
            left, right = self.portals[(index, neighbour)]
            if _area(left, right, target) >= 0.0:
                continue                    # not beyond this portal at all
            if _area(origin, target, left) * _area(origin, target, right) > 0.0:
                continue                    # the line passes it to one side
            found.append(neighbour)
        return found

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
        cells = self._search(first, last, origin, target)
        if not cells:
            return []
        return self._straightened(self._pull(origin, target, cells))

    def corridor(self, start: Sequence[float],
                 goal: Sequence[float]) -> List[int]:
        """The cells a route from ``start`` to ``goal`` crosses, in order.

        What the search answers before the line is pulled taut through it.
        Each cell shares an edge with the next, so a caller can walk the
        portals itself — to draw the search, to ask which rooms a route
        passes through, or to keep a bot's corridor and re-pull it as the bot
        moves.  A caller that just wants somewhere to walk wants :meth:`path`.
        """
        first = self.cell_at(start)
        last = self.cell_at(goal)
        if first is None or last is None:
            return []
        if first == last:
            return [first]
        return self._search(first, last, _point(start), _point(goal))

    def _search(self, first: int, last: int, start: Point,
                goal: Point) -> List[int]:
        """A* over the cells, costed along the line a walker would take.

        A step costs how much further the walker has to go to reach the portal
        it leaves by, measured to the **nearest point on that portal** rather
        than to the middle of it or to the next cell's centre.  Measured
        either of those ways a staircase of cells costs the same as the two
        sides it climbs, every run of cells between two places ties, and which
        one comes back is settled by the order the queue happened to fill.
        Since the funnel cannot leave the corridor it is given, that order
        would be the route.  Measured to the nearest point the diagonal is
        shorter, which is what it is.

        The state is the cell together with the portal it was entered by,
        because where a walker stands on arriving is what the next step is
        measured from.
        """
        begin: State = (first, -1)
        standing: Dict[State, Point] = {begin: start}
        best: Dict[State, float] = {begin: 0.0}
        came: Dict[State, State] = {}
        queue: List[Tuple[float, State]] = [(math.dist(start, goal), begin)]
        seen: set[State] = set()
        while queue:
            _estimate, state = heapq.heappop(queue)
            if state in seen:
                continue
            seen.add(state)
            cell, _entered = state
            if cell == last:
                return _walk_back(came, begin, state)
            here = standing[state]
            for neighbour in self.neighbours.get(cell, ()):
                step: State = (neighbour, cell)
                if step in seen:
                    continue
                gate = _nearest_on(self.portals[(cell, neighbour)], here)
                cost = best[state] + math.dist(here, gate)
                if cost < best.get(step, math.inf):
                    best[step] = cost
                    came[step] = state
                    standing[step] = gate
                    heapq.heappush(
                        queue, (cost + math.dist(gate, goal), step))
        return []

    def _straightened(self, corners: List[Point]) -> List[Point]:
        """Drop the corners the mesh lets the route see past.

        A corner the funnel planted stands either against the geometry or
        against the corridor, and only the first kind is a corner a walker
        has to make.  Each corner kept is the furthest one still in sight of
        the last, which can only shorten the route: the line between two
        corners is never longer than the way round the ones between them.
        """
        if len(corners) < 3:
            return corners
        kept: List[Point] = [corners[0]]
        index = 0
        while index < len(corners) - 1:
            index = self._furthest_seen(corners, index)
            kept.append(corners[index])
        return kept

    def _furthest_seen(self, corners: List[Point], index: int) -> int:
        """The last corner after ``index`` that can be walked to straight.

        The next one along always can -- the funnel put it there -- so this
        answers with at least ``index + 1`` and the walk always advances.
        """
        here = self.cell_at(corners[index])
        if here is not None:
            for step in range(len(corners) - 1, index + 1, -1):
                if self._reaches(here, corners[index], corners[step],
                                 STAND_REACH, STAND_TOLERANCE):
                    return step
        return index + 1

    def _pull(self, start: Point, goal: Point, cells: List[int]) -> List[Point]:
        """Pull the line taut through the portals the cells share.

        The simple stupid funnel: two edges of a cone are narrowed by each
        portal in turn, and a corner is planted whenever they cross.  Without
        it a path is a list of triangle centres, which on open floor is a
        zigzag across a room that has nothing in it.

        Each portal arrives in left-and-right order for the direction the
        route crosses it (:func:`_join`), which is the order the funnel needs.
        Working it out from the moving apex instead turns a portal round
        whenever the apex passes to the other side of it, and a funnel
        narrowing the wrong side of itself hands back a line that leaves the
        corridor entirely.
        """
        gates = [self.portals[(cells[index], cells[index + 1])]
                 for index in range(len(cells) - 1)]
        corners: List[Point] = [start]
        apex = left = right = start
        left_at = right_at = 0
        index = 0
        while index < len(gates) + 1:
            new_left, new_right = (gates[index] if index < len(gates)
                                   else (goal, goal))
            if _area(apex, right, new_right) <= 0.0:
                if _same(apex, right) or _area(apex, left, new_right) > 0.0:
                    right, right_at = new_right, index
                else:
                    corners.append(left)
                    apex = left = right = left
                    index = left_at
                    left_at = right_at = index
                    index += 1
                    continue
            if _area(apex, left, new_left) >= 0.0:
                if _same(apex, left) or _area(apex, right, new_left) < 0.0:
                    left, left_at = new_left, index
                else:
                    corners.append(right)
                    apex = left = right = right
                    index = right_at
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

def _join(points: np.ndarray, cells: np.ndarray) -> Tuple[
        Dict[int, List[int]], Dict[Tuple[int, int], Tuple[Point, Point]]]:
    """Neighbours and portals, by shared edge.

    Two cells are joined when they share two vertices **by position**, not by
    index.  A collision mesh built from a level is a triangle soup: the same
    corner appears once per triangle that touches it, with a different index
    each time, so matching indices joins nothing at all and every cell is an
    island with no way off it.  Positions are welded on a grid fine enough to
    be exact for geometry authored in map units and coarse enough to survive
    the arithmetic that got them into world space.

    A portal is stored **once per direction, in the order a walker crossing it
    that way meets its two ends**: left first.  Which end is which is a fact
    about the crossing rather than about the edge, and settling it here is what
    lets the funnel and the line-of-sight walk read a portal without working it
    out again -- and, since each of them asks about a portal from somewhere
    other than the cell it is leaving, without getting it wrong.
    """
    welded = _welded(points)
    centres = points[cells].mean(axis=1) if len(cells) else np.zeros((0, 3))
    edges: Dict[Tuple[int, int], List[int]] = {}
    for index, cell in enumerate(cells):
        for first, second in ((0, 1), (1, 2), (2, 0)):
            key = _edge(int(welded[int(cell[first])]),
                        int(welded[int(cell[second])]))
            edges.setdefault(key, []).append(index)
    neighbours: Dict[int, List[int]] = {index: [] for index in range(len(cells))}
    portals: Dict[Tuple[int, int], Tuple[Point, Point]] = {}
    for _key, sharing in edges.items():
        if len(sharing) != 2:
            continue
        left, right = sharing
        neighbours[left].append(right)
        neighbours[right].append(left)
        gate = _shared_edge(points, cells[left], cells[right], welded)
        portals[(left, right)] = _oriented(_point(centres[left]), gate)
        portals[(right, left)] = _oriented(_point(centres[right]), gate)
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
                 welded: np.ndarray) -> Tuple[Point, Point]:
    """The two corners two cells have in common, as positions.

    Taken from the cells rather than from the edge key, because the key is a
    welded id and what the funnel needs is a place.
    """
    theirs = {int(welded[int(index)]) for index in right}
    shared = [points[int(index)] for index in left
              if int(welded[int(index)]) in theirs]
    if len(shared) >= 2:
        return (_point(shared[0]), _point(shared[1]))
    return (_point(points[int(left[0])]), _point(points[int(left[1])]))


def _walk_back(came: Dict[State, State], first: State,
               last: State) -> List[int]:
    """The cells of a finished search, from ``first`` to ``last``."""
    route = [last]
    while route[-1] != first:
        route.append(came[route[-1]])
    route.reverse()
    return [cell for cell, _entered in route]


def _nearest_on(gate: Tuple[Point, Point], where: Spot) -> Point:
    """The point of a portal a walker at ``where`` reaches soonest."""
    one, other = gate
    run = (other[0] - one[0], other[1] - one[1], other[2] - one[2])
    span = run[0] * run[0] + run[1] * run[1] + run[2] * run[2]
    if span < _TINY:
        return one
    along = ((where[0] - one[0]) * run[0] + (where[1] - one[1]) * run[1]
             + (where[2] - one[2]) * run[2]) / span
    along = min(1.0, max(0.0, along))
    return (one[0] + run[0] * along, one[1] + run[1] * along,
            one[2] + run[2] * along)


# -- the funnel --------------------------------------------------------------

def _area(apex: Spot, one: Spot, other: Spot) -> float:
    """Twice the signed area of a triangle, seen from above.

    Positive when ``other`` is to the right of ``one`` about ``apex``, with
    +y up.  Seen from above because a funnel is a horizontal question: a
    path's height follows the floor and is not something to be pulled taut.
    """
    return float((one[0] - apex[0]) * (other[2] - apex[2])
                 - (other[0] - apex[0]) * (one[2] - apex[2]))


def _oriented(apex: Spot, gate: Tuple[Point, Point]) -> Tuple[Point, Point]:
    """A portal's endpoints as (left, right) seen from ``apex``."""
    one, other = gate
    if _area(apex, one, other) < 0.0:
        return (other, one)
    return (one, other)


def _same(one: Spot, other: Spot) -> bool:
    """Whether two points are the same place, to within the weld."""
    return math.dist(one, other) <= _INSIDE


def _tidied(corners: List[Point]) -> List[Point]:
    """Drop the corners that repeat, which a funnel plants at its own apex."""
    kept: List[Point] = []
    for corner in corners:
        if not kept or not _same(kept[-1], corner):
            kept.append(corner)
    return kept


def _inside_2d(corners: np.ndarray, where: Spot) -> bool:
    """Whether ``where`` is inside a triangle, seen from above."""
    a, b, c = corners
    first = _area(a, b, where)
    second = _area(b, c, where)
    third = _area(c, a, where)
    return (first >= -_INSIDE and second >= -_INSIDE and third >= -_INSIDE) or \
           (first <= _INSIDE and second <= _INSIDE and third <= _INSIDE)
