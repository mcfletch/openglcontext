"""Segments, points, boxes and solids against triangles -- NumPy only

The intersection tests X3D's pick sensors are answered with
(:mod:`OpenGLContext.scenegraph.x3dpicking`), each over whole arrays:

- :func:`segment_triangles`: where line segments cross triangles, every
  crossing with its parameter along the segment and its barycentric place on
  the triangle;
- :func:`inside_mesh`: which points are within a closed mesh, by the winding
  number, so the mesh may be wound either way;
- :func:`segment_box`: where segments enter an axis-aligned box, and the face
  they enter through;
- :class:`Box` and :func:`boxes_overlap`: two boxes, each any parallelepiped
  (a bounding box carried through a matrix), by separating axes;
- the solids a picking geometry is, :class:`BoxVolume`, :class:`SphereVolume`
  and :class:`MeshVolume`, each answering which points it contains and
  whether triangles meet it; :func:`cylinder_solid` and :func:`cone_solid`
  are those primitives' closed meshes, and :func:`target_meets` is a solid
  against a target's triangles.

Triangles are ``(n, 3, 3)`` arrays: n triangles of three corners. A point
that is not finite is never inside anything.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Optional, Protocol

import numpy as np

__all__ = [
    'Box', 'BoxEntries', 'BoxVolume', 'Crossings', 'MeshVolume', 'SphereVolume', 'Volume',
    'boxes_overlap', 'cone_solid', 'cylinder_solid', 'inside_mesh', 'segment_box',
    'segment_triangles', 'target_meets',
]

#: Below this a segment is taken as parallel to a triangle's plane, and an
#: axis built from two parallel edges is not tested.
EPSILON = 1e-12

#: How many pairs of segment and triangle are tested in one array operation.
CHUNK = 1 << 18


class Crossings(NamedTuple):
    """Where segments cross triangles, one entry per crossing

    segment, triangle -- which segment crossed which triangle
    t -- how far along the segment, 0 at its start and 1 at its end
    u, v -- the crossing's barycentric weights of the triangle's second and
        third corners
    """

    segment: np.ndarray
    triangle: np.ndarray
    t: np.ndarray
    u: np.ndarray
    v: np.ndarray


def _empty_crossings() -> Crossings:
    nothing = np.zeros(0)
    return Crossings(nothing.astype(np.intp), nothing.astype(np.intp), nothing, nothing, nothing)


def segment_triangles(starts: np.ndarray, ends: np.ndarray, triangles: np.ndarray) -> Crossings:
    """Every crossing of the segments from `starts` to `ends` with `triangles`

    A segment in the plane of a triangle crosses nothing in it.
    """
    starts = np.asarray(starts, dtype=np.float64).reshape(-1, 3)
    ends = np.asarray(ends, dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if not len(starts) or not len(triangles):
        return _empty_crossings()
    found = []
    rows = max(1, CHUNK // len(triangles))
    for first in range(0, len(starts), rows):
        found.append(_crossings(starts[first:first + rows], ends[first:first + rows],
                                triangles, first))
    return Crossings(*(np.concatenate(part) for part in zip(*found, strict=True)))


def _crossings(starts: np.ndarray, ends: np.ndarray, triangles: np.ndarray,
               offset: int) -> Crossings:
    """Möller and Trumbore's test, every segment of a chunk against every triangle"""
    direction = (ends - starts)[:, np.newaxis, :]
    corner = triangles[np.newaxis, :, 0]
    first = triangles[np.newaxis, :, 1] - corner
    second = triangles[np.newaxis, :, 2] - corner
    p = np.cross(direction, second)
    det = np.einsum('ijk,ijk->ij', first, p)
    usable = np.abs(det) > EPSILON
    inverse = np.where(usable, 1.0 / np.where(usable, det, 1.0), 0.0)
    offset_from = starts[:, np.newaxis, :] - corner
    u = np.einsum('ijk,ijk->ij', offset_from, p) * inverse
    q = np.cross(offset_from, first)
    v = np.einsum('ijk,ijk->ij', direction, q) * inverse
    t = np.einsum('ijk,ijk->ij', second, q) * inverse
    hit = usable & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t >= 0.0) & (t <= 1.0)
    segment, triangle = np.nonzero(hit)
    return Crossings(segment + offset, triangle, t[hit], u[hit], v[hit])


def inside_mesh(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Whether each of `points` is within the closed mesh of `triangles`

    By the generalised winding number (the sum of the triangles' solid
    angles about the point over 4 pi), whose magnitude is one inside a
    closed mesh and zero outside it.
    """
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    result = np.zeros(len(points), dtype=bool)
    finite = np.all(np.isfinite(points), axis=1)
    if not len(triangles) or not finite.any():
        return result
    chosen = np.nonzero(finite)[0]
    rows = max(1, CHUNK // len(triangles))
    for first in range(0, len(chosen), rows):
        indices = chosen[first:first + rows]
        result[indices] = np.abs(_winding(points[indices], triangles)) > 0.5
    return result


def _winding(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    a = triangles[np.newaxis, :, 0] - points[:, np.newaxis]
    b = triangles[np.newaxis, :, 1] - points[:, np.newaxis]
    c = triangles[np.newaxis, :, 2] - points[:, np.newaxis]
    la, lb, lc = (np.linalg.norm(each, axis=2) for each in (a, b, c))
    det = np.einsum('ijk,ijk->ij', a, np.cross(b, c))
    denominator = (la * lb * lc + np.einsum('ijk,ijk->ij', a, b) * lc
                   + np.einsum('ijk,ijk->ij', b, c) * la + np.einsum('ijk,ijk->ij', c, a) * lb)
    angles = 2.0 * np.arctan2(det, denominator)
    total: np.ndarray = angles.sum(axis=1) / (4.0 * math.pi)
    return total


class BoxEntries(NamedTuple):
    """Where segments enter a box, one entry per segment that reaches it

    segment -- which segment
    t -- how far along it, 0 where it starts inside
    normal -- the outward normal of the face it enters by; the face nearest
        its start where it starts inside
    """

    segment: np.ndarray
    t: np.ndarray
    normal: np.ndarray


def segment_box(starts: np.ndarray, ends: np.ndarray, low: np.ndarray,
                high: np.ndarray) -> BoxEntries:
    """Where each segment from `starts` to `ends` enters the box from `low` to `high`"""
    starts = np.asarray(starts, dtype=np.float64).reshape(-1, 3)
    direction = np.asarray(ends, dtype=np.float64).reshape(-1, 3) - starts
    low = np.asarray(low, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    moving = np.abs(direction) > EPSILON
    safe = np.where(moving, direction, 1.0)
    near = np.where(moving, np.minimum((low - starts) / safe, (high - starts) / safe), -np.inf)
    far = np.where(moving, np.maximum((low - starts) / safe, (high - starts) / safe), np.inf)
    within = moving | ((starts >= low) & (starts <= high))
    enter = near.max(axis=1)
    leave = far.min(axis=1)
    reaches = np.all(within, axis=1) & (enter <= leave) & (leave >= 0.0) & (enter <= 1.0)
    axis = near.argmax(axis=1)
    outside = enter > 0.0
    # Starting inside, the face nearest the start: the one it is deepest under
    depth = np.minimum(starts - low, high - starts)
    axis = np.where(outside, axis, depth.argmin(axis=1))
    side = np.where(outside, -np.sign(direction[np.arange(len(starts)), axis]),
                    np.where((starts - low)[np.arange(len(starts)), axis]
                             < (high - starts)[np.arange(len(starts)), axis], -1.0, 1.0))
    normal = np.zeros_like(starts)
    normal[np.arange(len(starts)), axis] = side
    chosen = np.nonzero(reaches)[0]
    return BoxEntries(chosen, np.maximum(enter[chosen], 0.0), normal[chosen])


class Box(NamedTuple):
    """A box with any three edge directions: a centre, and three half-edges as rows"""

    centre: np.ndarray
    edges: np.ndarray

    @classmethod
    def from_bounds(cls, low: np.ndarray, high: np.ndarray, matrix: np.ndarray) -> Box:
        """The box from `low` to `high` carried by the row-vector `matrix`"""
        low = np.asarray(low, dtype=np.float64)
        high = np.asarray(high, dtype=np.float64)
        matrix = np.asarray(matrix, dtype=np.float64)
        centre = (low + high) / 2.0 @ matrix[:3, :3] + matrix[3, :3]
        return cls(centre, np.diag((high - low) / 2.0) @ matrix[:3, :3])

    @property
    def low(self) -> np.ndarray:
        found: np.ndarray = self.centre - np.abs(self.edges).sum(axis=0)
        return found

    @property
    def high(self) -> np.ndarray:
        found: np.ndarray = self.centre + np.abs(self.edges).sum(axis=0)
        return found


def boxes_overlap(first: Box, second: Box) -> bool:
    """Whether two boxes share any space, by the fifteen separating axes"""
    axes = [first.edges[0], first.edges[1], first.edges[2],
            second.edges[0], second.edges[1], second.edges[2]]
    faces = [np.cross(box.edges[i], box.edges[j]) for box in (first, second)
             for i, j in ((0, 1), (1, 2), (2, 0))]
    crossed = [np.cross(a, b) for a in first.edges for b in second.edges]
    between = second.centre - first.centre
    for axis in axes + faces + crossed:
        if np.dot(axis, axis) < EPSILON:
            continue
        reach = np.abs(first.edges @ axis).sum() + np.abs(second.edges @ axis).sum()
        if abs(float(np.dot(between, axis))) > reach:
            return False
    return True


class Volume(Protocol):
    """A solid a picking geometry is, in the sensor's coordinates"""

    low: np.ndarray
    high: np.ndarray

    @property
    def centre(self) -> np.ndarray: ...

    def contains(self, points: np.ndarray) -> np.ndarray: ...

    def meets(self, triangles: np.ndarray) -> bool: ...


class BoxVolume:
    """X3D's Box as a solid: centred on the origin, `half` its half-size"""

    def __init__(self, half: np.ndarray) -> None:
        self.half = np.abs(np.asarray(half, dtype=np.float64))
        self.low = -self.half
        self.high = self.half

    @property
    def centre(self) -> np.ndarray:
        return np.zeros(3)

    def contains(self, points: np.ndarray) -> np.ndarray:
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        with np.errstate(invalid='ignore'):
            inside: np.ndarray = np.all(np.abs(points) <= self.half, axis=1)
        return inside

    def meets_each(self, triangles: np.ndarray) -> np.ndarray:
        """Whether each triangle shares a point with the box, by separating axes"""
        triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        edges = np.stack([triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 1],
                          triangles[:, 0] - triangles[:, 2]], axis=1)
        axes = [np.broadcast_to(np.identity(3)[i], (len(triangles), 3)) for i in range(3)]
        axes.append(np.cross(edges[:, 0], edges[:, 1]))
        for box_axis in np.identity(3):
            for edge in range(3):
                axes.append(np.cross(box_axis, edges[:, edge]))
        apart = np.zeros(len(triangles), dtype=bool)
        for axis in axes:
            projected = np.einsum('ijk,ik->ij', triangles, axis)
            reach = np.abs(axis) @ self.half
            usable = np.einsum('ij,ij->i', axis, axis) > EPSILON
            apart |= usable & ((projected.min(axis=1) > reach) | (projected.max(axis=1) < -reach))
        meets: np.ndarray = ~apart
        return meets

    def meets(self, triangles: np.ndarray) -> bool:
        return bool(self.meets_each(triangles).any())


class SphereVolume:
    """X3D's Sphere as a solid: centred on the origin"""

    def __init__(self, radius: float) -> None:
        self.radius = abs(float(radius))
        self.high = np.full(3, self.radius)
        self.low = -self.high

    @property
    def centre(self) -> np.ndarray:
        return np.zeros(3)

    def contains(self, points: np.ndarray) -> np.ndarray:
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        with np.errstate(invalid='ignore'):
            inside: np.ndarray = np.einsum('ij,ij->i', points, points) <= self.radius ** 2
        return inside

    def meets_each(self, triangles: np.ndarray) -> np.ndarray:
        """Whether each triangle's nearest point to the centre is within the radius"""
        triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        return _nearest_distance(triangles) <= self.radius

    def meets(self, triangles: np.ndarray) -> bool:
        return bool(self.meets_each(triangles).any())


def _segment_distance(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """The distance from the origin to each segment"""
    along = end - start
    length = np.einsum('ij,ij->i', along, along)
    t = np.clip(-np.einsum('ij,ij->i', start, along) / np.where(length > 0, length, 1.0), 0.0, 1.0)
    nearest = start + along * t[:, np.newaxis]
    distance: np.ndarray = np.linalg.norm(nearest, axis=1)
    return distance


def _nearest_distance(triangles: np.ndarray) -> np.ndarray:
    """The distance from the origin to the nearest point of each triangle"""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    distance = np.minimum(np.minimum(_segment_distance(a, b), _segment_distance(b, c)),
                          _segment_distance(c, a))
    normal = np.cross(b - a, c - a)
    area = np.einsum('ij,ij->i', normal, normal)
    flat = area > EPSILON
    unit = normal / np.sqrt(np.where(flat, area, 1.0))[:, np.newaxis]
    plane = np.einsum('ij,ij->i', a, unit)
    foot = unit * plane[:, np.newaxis]
    # The foot of the perpendicular is within the triangle where it is on the
    # inner side of each edge
    within = flat.copy()
    for first, second in ((a, b), (b, c), (c, a)):
        within &= np.einsum('ij,ij->i', np.cross(second - first, foot - first), normal) >= 0.0
    nearest: np.ndarray = np.where(within, np.minimum(distance, np.abs(plane)), distance)
    return nearest


class MeshVolume:
    """A closed mesh as a solid"""

    def __init__(self, triangles: np.ndarray) -> None:
        self.triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        corners = self.triangles.reshape(-1, 3)
        self.low = corners.min(axis=0) if len(corners) else np.zeros(3)
        self.high = corners.max(axis=0) if len(corners) else np.zeros(3)

    @property
    def centre(self) -> np.ndarray:
        middle: np.ndarray = (self.low + self.high) / 2.0
        return middle

    def contains(self, points: np.ndarray) -> np.ndarray:
        return inside_mesh(points, self.triangles)

    def meets(self, triangles: np.ndarray) -> bool:
        """Whether a corner of `triangles` is within the mesh, or the surfaces cross"""
        triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        if not len(triangles) or not len(self.triangles):
            return False
        if self.contains(triangles.reshape(-1, 3)).any():
            return True
        return _surfaces_cross(self.triangles, triangles)


def _edges(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    starts = triangles.reshape(-1, 3)
    ends = triangles[:, [1, 2, 0]].reshape(-1, 3)
    return starts, ends


def _surfaces_cross(first: np.ndarray, second: np.ndarray) -> bool:
    """Whether an edge of either set of triangles passes through the other"""
    for edges_of, through in ((first, second), (second, first)):
        starts, ends = _edges(edges_of)
        if len(segment_triangles(starts, ends, through).t):
            return True
    return False


def target_meets(volume: Volume, triangles: np.ndarray) -> bool:
    """Whether `volume` meets a target of `triangles`: touches them, or is inside them

    Inside is by the winding number (:func:`inside_mesh`), which for an open
    surface is where it winds more than half way round.
    """
    triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if not len(triangles):
        return False
    if volume.meets(triangles):
        return True
    return bool(inside_mesh(volume.centre[np.newaxis], triangles)[0])


def _ring(radius: float, y: float, sides: int) -> np.ndarray:
    angle = np.linspace(0.0, 2.0 * math.pi, sides, endpoint=False)
    return np.column_stack([radius * np.sin(angle), np.full(sides, y), radius * np.cos(angle)])


def _solid(bottom: np.ndarray, top: Optional[np.ndarray], apex: float, base: float) -> np.ndarray:
    """A closed solid over a ring `bottom`: walls up to the ring `top`, or to an apex"""
    sides = len(bottom)
    following = np.roll(np.arange(sides), -1)
    centre_base = np.array([0.0, base, 0.0])
    parts = [np.stack([np.broadcast_to(centre_base, bottom.shape), bottom[following], bottom],
                      axis=1)]
    if top is None:
        tip = np.array([0.0, apex, 0.0])
        parts.append(np.stack([bottom, bottom[following], np.broadcast_to(tip, bottom.shape)],
                              axis=1))
    else:
        centre_top = np.array([0.0, apex, 0.0])
        parts.append(np.stack([bottom, bottom[following], top[following]], axis=1))
        parts.append(np.stack([bottom, top[following], top], axis=1))
        parts.append(np.stack([np.broadcast_to(centre_top, top.shape), top, top[following]],
                              axis=1))
    return np.concatenate(parts)


def cylinder_solid(radius: float, height: float, sides: int = 32) -> np.ndarray:
    """X3D's Cylinder as a closed mesh of `sides` walls: about the y axis, centred"""
    half = height / 2.0
    return _solid(_ring(radius, -half, sides), _ring(radius, half, sides), half, -half)


def cone_solid(bottomRadius: float, height: float, sides: int = 32) -> np.ndarray:
    """X3D's Cone as a closed mesh of `sides` walls: its apex up the y axis, centred"""
    half = height / 2.0
    return _solid(_ring(bottomRadius, -half, sides), None, half, -half)
