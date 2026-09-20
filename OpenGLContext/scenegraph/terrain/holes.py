"""Ground that is not there: cutting a surface back to the edge of an opening.

A height field is a surface, so a hill with a road running *inside* it has no
way to say it is hollow. ``holes(x, z) -> mask`` is that way, and :func:`cut` is
what a mesh does with one: the triangles the opening's edge crosses are cut on
that edge, and what is left of them is kept.

The rule, whole:

* a triangle the edge crosses is cut along it: the corners in the opening go,
  the crossings on its edges become corners, and what is left is triangulated;
* a triangle with every corner in an opening goes;
* anything else -- a triangle no edge crossed, and each piece a cut left --
  goes if its *centre* is in an opening. An opening smaller than a cell has no
  crossing to catch it, and a triangle with an opening through the middle of it
  is a triangle over a hole.

The edge itself is found by halving. The opening answers yes or no, so where it
starts is where the answer changes, and :data:`CROSSING_STEPS` halvings put that
inside a millimetre of a metres-wide cell. A crossing belongs to the *edge*
rather than to the triangle that asked for it, so the two triangles sharing an
edge are handed the same corner and the cut surface has no crack down it.

Every vertex attribute is carried across, not only the position: a new corner's
normal, colour or texture coordinate is the one the surface already had there,
so cutting a cell changes where the ground ends and nothing else about it.

What the cut resolves is set by the grid it is cutting. An opening wider than a
cell has its edge followed wherever that edge crosses one. Detail *finer* than a
cell -- an opening smaller than one, or a corner where the edge turns inside one
-- is resolved to the triangle it falls in: a triangle has three corners to ask
about, and a straight line between each pair of them. The centre rule is what
decides there, so the ground goes back a triangle at a time rather than reaching
into the opening.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

__all__ = ['cut', 'CROSSING_STEPS']

#: How many times an edge is halved to find where an opening crosses it. Twelve
#: puts the crossing within a four-thousandth of the edge, which on a two-metre
#: cell is under a millimetre -- finer than the float32 a vertex is drawn from
#: holds at world scale.
CROSSING_STEPS = 12

Holes = Callable[[Any, Any], Any]


def cut(vertices: Any, triangles: Any, holes: Holes,
        steps: int = CROSSING_STEPS) -> "tuple[np.ndarray, np.ndarray]":
    """Trim a triangle mesh back to the edge of the openings in it.

    :param vertices: ``(V, K)`` vertex rows whose first three columns are the
        world position. Anything after them -- a normal, a colour -- is carried
        across interpolated.
    :param triangles: ``(T, 3)`` indices into ``vertices``.
    :param holes: ``holes(x, z) -> mask`` over arrays of world positions, true
        where the ground is not there.
    :param steps: how many halvings locate a crossing on an edge.

    :returns: ``(vertices, triangles)``. The vertices given come back unchanged
        and in place -- an index into them still means what it meant -- with the
        corners the cut needed appended after them.
    """
    vertices = np.asarray(vertices)
    triangles = np.asarray(triangles).reshape(-1, 3)
    if not len(triangles):
        return vertices, triangles
    position = np.asarray(vertices[:, :3], 'd')
    inside = np.asarray(holes(position[:, 0], position[:, 2]), bool)
    corners = inside[triangles]
    count = corners.sum(axis=1)

    whole = count == 0
    if whole.any():
        # The centre rule, and only where it can still decide anything: a
        # triangle the edge crosses is cut on the edge instead.
        covered = np.asarray(holes(*_middles(position, triangles[whole])), bool)
        whole[np.flatnonzero(whole)[covered]] = False

    crossed = (count == 1) | (count == 2)
    if not crossed.any():
        return vertices, triangles[whole]

    corner, edges, at = _crossings(vertices, position, inside,
                                   triangles[crossed], holes, steps)
    vertices = np.concatenate([vertices, corner])
    trimmed = _trimmed(triangles[crossed], corners[crossed], count[crossed],
                       edges, at)
    # An opening whose edge runs along a grid line crosses it at a vertex that
    # is already there, and the triangle beside it closes to nothing.
    flat = ((trimmed[:, 0] == trimmed[:, 1]) | (trimmed[:, 1] == trimmed[:, 2])
            | (trimmed[:, 2] == trimmed[:, 0]))
    trimmed = trimmed[~flat]
    # The centre rule again, over what the cut left. An edge is followed with a
    # straight line across each triangle it crosses, and where the opening turns
    # inside one -- a corner of it, or a cell as wide as the opening itself --
    # the line leaves ground behind that is in the opening. What is left is
    # measured by the rule that decided everything else.
    covered = np.asarray(
        holes(*_middles(np.asarray(vertices[:, :3], 'd'), trimmed)), bool)
    pieces = [piece for piece in (triangles[whole], trimmed[~covered])
              if len(piece)]
    if not pieces:
        return vertices, triangles[:0]
    return vertices, np.concatenate(pieces)


def _middles(position: np.ndarray, triangles: np.ndarray
             ) -> "tuple[np.ndarray, np.ndarray]":
    """Where each triangle sits in the ground plane, as ``(x, z)``.

    Gathered a column at a time: a world's ground is millions of triangles, and
    taking all three coordinates of all three corners to average two of them
    holds four times the array this does.
    """
    def across(column: int) -> np.ndarray:
        each = position[:, column]
        found: np.ndarray = (each[triangles[:, 0]] + each[triangles[:, 1]]
                             + each[triangles[:, 2]]) / 3.0
        return found
    return across(0), across(2)


def _crossings(vertices: np.ndarray, position: np.ndarray, inside: np.ndarray,
               triangles: np.ndarray, holes: Holes, steps: int
               ) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Where the opening crosses each edge that it crosses.

    Answered per *edge*, keyed on the two vertices it joins with the lower index
    first, so an edge two triangles share is halved once and both are handed the
    same corner. The interval starts as the whole edge and is halved ``steps``
    times, each time keeping the half whose ends still disagree.

    :returns: the corners to append to the mesh, the edges they were cut on, and
        the vertex index to use for each of those edges -- which is one of the
        edge's own ends where the crossing landed on it, and a new corner
        otherwise.
    """
    ends = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]],
                           triangles[:, [2, 0]]])
    ends = ends[inside[ends[:, 0]] != inside[ends[:, 1]]]
    edges = np.unique(np.stack([ends.min(axis=1), ends.max(axis=1)], axis=-1),
                      axis=0)

    start, finish = position[edges[:, 0]], position[edges[:, 1]]
    at_start = inside[edges[:, 0]]
    near = np.zeros(len(edges))
    far = np.ones(len(edges))
    for _ in range(steps):
        middle = 0.5 * (near + far)
        probe = start + (finish - start) * middle[:, None]
        same = np.asarray(holes(probe[:, 0], probe[:, 2]), bool) == at_start
        near = np.where(same, middle, near)
        far = np.where(same, far, middle)
    # The end of the interval that is *outside* the opening, rather than the
    # middle of it: a corner is then a point the opening itself answered no to,
    # so the ground that is left never reaches into it.
    along = np.where(at_start, far, near)

    # A crossing this close to an end of the edge is at that end: an opening
    # whose edge follows a grid line crosses it where a vertex already stands,
    # and a corner of its own there would be a sliver a fraction of a
    # millimetre wide rather than a cut.
    grain = 2.0 ** -steps
    on_end = (along <= grain) | (along >= 1.0 - grain)
    at = np.where(along <= grain, edges[:, 0], edges[:, 1]).astype('q')
    fresh = np.flatnonzero(~on_end)
    at[fresh] = len(vertices) + np.arange(len(fresh))

    low = np.asarray(vertices[edges[fresh, 0]], 'd')
    corner = low + ((np.asarray(vertices[edges[fresh, 1]], 'd') - low)
                    * along[fresh][:, None])
    return corner.astype(vertices.dtype), edges, at


def _trimmed(triangles: np.ndarray, corners: np.ndarray, count: np.ndarray,
             edges: np.ndarray, at: np.ndarray) -> np.ndarray:
    """What is left of the triangles the opening's edge runs through.

    Each is turned so the odd corner out comes first: the one corner in the
    opening, or the one corner left outside it. The opening then crosses the two
    edges that meet there, and the winding is the winding the triangle had,
    since each corner that goes is replaced where it stood. One corner in the
    opening leaves a quadrilateral, which is two triangles; two corners in it
    leave one.
    """
    rows = np.arange(len(triangles))
    odd = np.where(count == 1, corners.argmax(axis=1), corners.argmin(axis=1))
    a = triangles[rows, odd]
    b = triangles[rows, (odd + 1) % 3]
    c = triangles[rows, (odd + 2) % 3]
    entering = at[_row_of(edges, a, b)]
    leaving = at[_row_of(edges, c, a)]

    one = count == 1
    quad = np.stack([entering[one], b[one], c[one],
                     entering[one], c[one], leaving[one]], axis=-1)
    two = ~one
    corner = np.stack([a[two], entering[two], leaving[two]], axis=-1)
    return np.concatenate([quad.reshape(-1, 3), corner.reshape(-1, 3)]
                          ).astype(triangles.dtype)


def _row_of(edges: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Which row of ``edges`` joins each pair of vertices.

    ``edges`` comes from :func:`numpy.unique`, so it is sorted by its low index
    and then its high one; one number built the same way is enough to look a
    pair up in it.
    """
    span = int(edges.max()) + 1
    key = np.minimum(a, b).astype('q') * span + np.maximum(a, b)
    found: np.ndarray = np.searchsorted(
        edges[:, 0].astype('q') * span + edges[:, 1], key)
    return found
