"""X3D's triangle and line sets as glTF-shaped arrays -- NumPy only, no GL

The first group of functions turns a set's own fields (`fanCount`,
`stripCount`, `index`, `vertexCount`) into rows of coordinate indices: three
per triangle, two per line segment. :func:`composed_arrays` turns those and the
set's `Coordinate`, `Normal`, `Color`/`ColorRGBA` and texture coordinates into
the attribute arrays a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` is
built from, keyed by glTF semantic, which is what
:func:`~OpenGLContext.scenegraph.frommesh.mesh_from_primitive` reads.

X3D's rules (ISO/IEC 19775-1, 11.2 and 11.4): the attributes of a composed
set are indexed as its coordinates are; `colorPerVertex` and `normalPerVertex`
false give one value per triangle; normals that are not given are generated,
averaged across the triangles that share a coordinate where `normalPerVertex`
is true and flat where it is false; `ccw` false means the triangles are wound
clockwise as seen from their front.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from numpy.typing import ArrayLike

from OpenGLContext.scenegraph import x3dglsl

__all__ = ['ComposedArrays', 'arc_close', 'arc_points', 'arc_sweep', 'composed_arrays',
           'crease_normals', 'disk', 'fans', 'grid_points', 'grid_texcoords',
           'grid_triangles', 'indexed_fans', 'indexed_quads', 'indexed_strips',
           'indexed_triangles', 'line_segments', 'per_quad', 'quad_set', 'quads',
           'rectangle', 'split_index', 'strips', 'triangle_set', 'triangle_set_2d',
           'vertex_normals']

_NO_TRIANGLES = np.zeros((0, 3), np.int64)


def triangle_set(count: int) -> np.ndarray:
    """A `TriangleSet`'s triangles: its points three at a time"""
    usable = (int(count) // 3) * 3
    return np.arange(usable, dtype=np.int64).reshape(-1, 3)


def indexed_triangles(index: ArrayLike) -> np.ndarray:
    """An `IndexedTriangleSet`'s triangles: its index three at a time"""
    flat = np.asarray(index, dtype=np.int64).ravel()
    return flat[:(len(flat) // 3) * 3].reshape(-1, 3)


def quads(corners: np.ndarray) -> np.ndarray:
    """Two triangles for each row of four `corners`, split from the first corner"""
    corners = np.asarray(corners, dtype=np.int64).reshape(-1, 4)
    return corners[:, [0, 1, 2, 0, 2, 3]].reshape(-1, 3)


def quad_set(count: int) -> np.ndarray:
    """A `QuadSet`'s triangles: its points four at a time, two triangles a quad"""
    return quads(np.arange((int(count) // 4) * 4, dtype=np.int64))


def indexed_quads(index: ArrayLike) -> np.ndarray:
    """An `IndexedQuadSet`'s triangles: its index four at a time, two triangles a quad"""
    flat = np.asarray(index, dtype=np.int64).ravel()
    return quads(flat[:(len(flat) // 4) * 4])


def fans(counts: ArrayLike) -> np.ndarray:
    """Triangle fans of `counts` points each, the points taken in order

    Each fan turns about its first point. A fan of fewer than three points
    makes no triangle.
    """
    found = []
    start = 0
    for count in (int(value) for value in np.asarray(counts).ravel()):
        if count >= 3:
            step = np.arange(1, count - 1, dtype=np.int64)
            found.append(np.stack([np.full(count - 2, start), start + step,
                                   start + step + 1], axis=1))
        start += max(count, 0)
    return np.concatenate(found) if found else _NO_TRIANGLES


def strips(counts: ArrayLike) -> np.ndarray:
    """Triangle strips of `counts` points each, the points taken in order

    Every other triangle of a strip is wound the other way round, so that all
    of them face the way the first does.
    """
    found = []
    start = 0
    for count in (int(value) for value in np.asarray(counts).ravel()):
        if count >= 3:
            step = np.arange(count - 2, dtype=np.int64)
            odd = (step % 2).astype(bool)
            first = np.where(odd, start + step + 1, start + step)
            second = np.where(odd, start + step, start + step + 1)
            found.append(np.stack([first, second, start + step + 2], axis=1))
        start += max(count, 0)
    return np.concatenate(found) if found else _NO_TRIANGLES


def split_index(index: ArrayLike) -> "tuple[np.ndarray, list[int]]":
    """An index of runs separated by -1, as the runs' indices end to end and their lengths"""
    flat = np.asarray(index, dtype=np.int64).ravel()
    breaks = np.flatnonzero(flat == -1)
    bounds = np.concatenate([[-1], breaks, [len(flat)]])
    counts = [int(end - begin - 1) for begin, end in zip(bounds[:-1], bounds[1:])]
    return flat[flat != -1], [count for count in counts if count > 0]


def indexed_fans(index: ArrayLike) -> np.ndarray:
    """An `IndexedTriangleFanSet`'s triangles: one fan per run of its index"""
    flat, counts = split_index(index)
    return flat[fans(counts)] if counts else _NO_TRIANGLES


def indexed_strips(index: ArrayLike) -> np.ndarray:
    """An `IndexedTriangleStripSet`'s triangles: one strip per run of its index"""
    flat, counts = split_index(index)
    return flat[strips(counts)] if counts else _NO_TRIANGLES


def line_segments(counts: ArrayLike) -> np.ndarray:
    """A `LineSet`'s segments: polylines of `counts` points each, taken in order"""
    found = []
    start = 0
    for count in (int(value) for value in np.asarray(counts).ravel()):
        if count >= 2:
            step = np.arange(count - 1, dtype=np.int64)
            found.append(np.stack([start + step, start + step + 1], axis=1))
        start += max(count, 0)
    return np.concatenate(found) if found else np.zeros((0, 2), np.int64)


def grid_points(height: ArrayLike, x_dimension: int, z_dimension: int,
                x_spacing: float, z_spacing: float) -> np.ndarray:
    """An `ElevationGrid`'s points: column i, row j at (i * xSpacing, height, j * zSpacing)"""
    column, row = np.meshgrid(np.arange(x_dimension), np.arange(z_dimension))
    heights = np.asarray(height, dtype=np.float32).ravel()[:x_dimension * z_dimension]
    return np.stack([column.ravel() * float(x_spacing), heights,
                     row.ravel() * float(z_spacing)], axis=1).astype(np.float32)


def grid_triangles(x_dimension: int, z_dimension: int) -> np.ndarray:
    """An `ElevationGrid`'s triangles, two per quad, facing +y when wound counter-clockwise"""
    if x_dimension < 2 or z_dimension < 2:
        return _NO_TRIANGLES
    column, row = np.meshgrid(np.arange(x_dimension - 1), np.arange(z_dimension - 1))
    near = (column + row * x_dimension).ravel()
    far = near + x_dimension
    first = np.stack([near, far, far + 1], axis=1)
    second = np.stack([near, far + 1, near + 1], axis=1)
    return np.stack([first, second], axis=1).reshape(-1, 3).astype(np.int64)


def grid_texcoords(x_dimension: int, z_dimension: int) -> np.ndarray:
    """An `ElevationGrid`'s default texture coordinates: 0 to 1 across, 0 to 1 down"""
    s = np.linspace(0.0, 1.0, x_dimension) if x_dimension > 1 else np.zeros(1)
    t = np.linspace(0.0, 1.0, z_dimension) if z_dimension > 1 else np.zeros(1)
    column, row = np.meshgrid(s, t)
    return np.stack([column.ravel(), row.ravel()], axis=1).astype(np.float32)


def per_quad(values: ArrayLike) -> np.ndarray:
    """One value per quad of a grid, as one per triangle of :func:`grid_triangles`"""
    return np.repeat(np.asarray(values), 2, axis=0)


def crease_normals(points: np.ndarray, triangles: np.ndarray, crease_angle: float) -> np.ndarray:
    """One normal per triangle corner, smoothed across faces meeting within `crease_angle`

    A corner's normal averages the normals of the triangles sharing its point
    whose angle to its own triangle is under `crease_angle` (radians); a
    sharper fold stays sharp.
    """
    faces = _face_normals(points, triangles)
    corner_vertex = triangles.ravel()
    corner_face = np.repeat(np.arange(len(triangles)), 3)
    order = np.argsort(corner_vertex, kind='stable')
    by_vertex = corner_vertex[order]
    starts = np.searchsorted(by_vertex, corner_vertex, 'left')
    degree = np.searchsorted(by_vertex, corner_vertex, 'right') - starts
    pair_corner = np.repeat(np.arange(len(corner_vertex)), degree)
    offset = np.arange(int(degree.sum())) - np.repeat(np.cumsum(degree) - degree, degree)
    pair_face = corner_face[order[np.repeat(starts, degree) + offset]]
    own = faces[corner_face[pair_corner]]
    near = (own * faces[pair_face]).sum(axis=1) >= np.cos(float(crease_angle)) - 1e-6
    sums = np.zeros((len(corner_vertex), 3), np.float64)
    np.add.at(sums, pair_corner[near], faces[pair_face[near]])
    length = np.linalg.norm(sums, axis=1, keepdims=True)
    empty = ~(length[:, 0] > 0)
    length[empty] = 1.0
    found = sums / length
    found[empty] = faces[corner_face[empty]]
    smoothed: np.ndarray = np.nan_to_num(found).astype(np.float32)
    return smoothed


def arc_sweep(start: float, end: float) -> float:
    """How far an X3D arc turns, counter-clockwise from `start` to `end`, in radians

    The same start and end, or a whole turn between them, is a circle.
    """
    sweep = (float(end) - float(start)) % (2.0 * math.pi)
    return sweep if sweep > 1e-12 else 2.0 * math.pi


def arc_points(radius: float, start: float, end: float, segments: int) -> np.ndarray:
    """Points along an arc in the z=0 plane, `segments` + 1 of them from start to end"""
    angles = float(start) + np.linspace(0.0, arc_sweep(start, end), max(int(segments), 1) + 1)
    return np.stack([np.cos(angles) * radius, np.sin(angles) * radius,
                     np.zeros_like(angles)], axis=1).astype(np.float32)


def default_texcoords(points: ArrayLike, bounds: Optional[ArrayLike] = None) -> np.ndarray:
    """X3D's texture coordinates for a face set with no texCoord, one per point

    s runs from 0 to 1 along the largest dimension of the bounding box of
    `bounds` (default `points`), t along the second largest, from 0 to its
    size over the largest's; ties go to X, then Y, then Z.
    """
    found = np.asarray(points, np.float64).reshape(-1, 3)
    box = found if bounds is None else np.asarray(bounds, np.float64).reshape(-1, 3)
    if not len(found) or not len(box):
        return np.zeros((len(found), 2), np.float32)
    low = box.min(axis=0)
    size = box.max(axis=0) - low
    # A stable sort of the negated sizes keeps X before Y before Z among equals
    largest, second = np.argsort(-size, kind='stable')[:2]
    scale = size[largest] if size[largest] > 0 else 1.0
    return ((found[:, [largest, second]] - low[[largest, second]]) / scale).astype(np.float32)


def _flat_texcoords(points: np.ndarray, low: ArrayLike, high: ArrayLike) -> np.ndarray:
    """Points' x and y across a box, as texture coordinates from 0 to 1"""
    bottom, top = np.asarray(low, np.float64), np.asarray(high, np.float64)
    span = np.where(top - bottom > 0, top - bottom, 1.0)
    found: np.ndarray = ((points[:, :2] - bottom) / span).astype(np.float32)
    return found


def rectangle(size: ArrayLike) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """A `Rectangle2D`: points, triangles and texture coordinates, centred on the origin"""
    half_x, half_y = (float(value) / 2.0 for value in np.asarray(size).ravel()[:2])
    points = np.array([(-half_x, -half_y, 0), (half_x, -half_y, 0), (half_x, half_y, 0),
                       (-half_x, half_y, 0)], np.float32)
    texcoords = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], np.float32)
    return points, np.array([[0, 1, 2], [0, 2, 3]], np.int64), texcoords


def disk(inner: float, outer: float, segments: int) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """A `Disk2D`: a fan round the centre, or a ring where `inner` is above 0"""
    count = max(int(segments), 3)
    ring = arc_points(outer, 0.0, 2.0 * math.pi, count)[:-1]
    step = np.arange(count)
    if inner <= 0.0:
        points = np.concatenate([np.zeros((1, 3), np.float32), ring])
        triangles = np.stack([np.zeros(count, np.int64), step + 1, (step + 1) % count + 1], axis=1)
    else:
        points = np.concatenate([ring, arc_points(inner, 0.0, 2.0 * math.pi, count)[:-1]])
        following = (step + 1) % count
        triangles = np.concatenate([
            np.stack([step + count, step, following], axis=1),
            np.stack([step + count, following, following + count], axis=1),
        ]).astype(np.int64)
    return points, triangles, _flat_texcoords(points, (-outer, -outer), (outer, outer))


def arc_close(radius: float, start: float, end: float, closure: str,
              segments: int) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """An `ArcClose2D`: closed through the centre ('PIE') or across its ends ('CHORD')"""
    count = max(int(segments), 1)
    arc = arc_points(radius, start, end, count)
    step = np.arange(count)
    if str(closure).upper() == 'CHORD':
        points = arc
        inner = np.arange(1, count, dtype=np.int64)
        triangles = np.stack([np.zeros(len(inner), np.int64), inner, inner + 1], axis=1)
    else:
        points = np.concatenate([np.zeros((1, 3), np.float32), arc])
        triangles = np.stack([np.zeros(count, np.int64), step + 1, step + 2], axis=1)
    return points, triangles, _flat_texcoords(points, (-radius, -radius), (radius, radius))


def triangle_set_2d(vertices: ArrayLike) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """A `TriangleSet2D`: its vertices three at a time, textured across their bounds"""
    flat = np.asarray(vertices, np.float32).reshape(-1, 2)
    points = np.concatenate([flat, np.zeros((len(flat), 1), np.float32)], axis=1)
    low = flat.min(axis=0) if len(flat) else (0.0, 0.0)
    high = flat.max(axis=0) if len(flat) else (1.0, 1.0)
    return points, triangle_set(len(points)), _flat_texcoords(points, low, high)


@dataclass
class ComposedArrays:
    """A composed set's arrays, as :func:`~OpenGLContext.scenegraph.frommesh.mesh_from_primitive` reads them"""

    #: Arrays by glTF semantic: POSITION, NORMAL, TANGENT, COLOR_0, TEXCOORD_n.
    attributes: "dict[str, np.ndarray]"
    #: Triangle corners into the arrays, or None where every corner has its own vertex.
    indices: Optional[np.ndarray]
    #: Triangles left out for naming a coordinate the set does not have.
    dropped: int = 0
    #: Attributes left out for holding fewer values than they are indexed by.
    short: "list[str]" = field(default_factory=list)
    #: The glTF primitive mode: triangles.
    mode: int = 4
    #: X3D's `attrib` vertex attributes, (name, one row a vertex, locations)
    #: each, for a shader reading them by name.
    vertex_attributes: "list[tuple[str, np.ndarray, int]]" = field(default_factory=list)


def _face_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    first, second, third = (points[triangles[:, corner]] for corner in range(3))
    with np.errstate(invalid='ignore'):
        cross = np.cross(second - first, third - first)
        length = np.linalg.norm(cross, axis=1, keepdims=True)
        length[~(length > 0)] = 1.0
        normals: np.ndarray = np.nan_to_num(cross / length).astype(np.float32)
    return normals


def vertex_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Normals averaged across the triangles that share each point"""
    sums = np.zeros((len(points), 3), np.float64)
    faces = _face_normals(points, triangles)
    for corner in range(3):
        np.add.at(sums, triangles[:, corner], faces)
    length = np.linalg.norm(sums, axis=1, keepdims=True)
    length[~(length > 0)] = 1.0
    return np.nan_to_num(sums / length).astype(np.float32)


def composed_arrays(
    points: Any, triangles: np.ndarray, *, ccw: bool = True,
    normals: Any = None, normal_per_vertex: bool = True,
    colors: Any = None, color_per_vertex: bool = True,
    texcoords: Sequence[Any] = (), tangents: Any = None,
    crease_angle: Optional[float] = None,
    vertex_attributes: Sequence["tuple[str, np.ndarray, int]"] = (),
) -> ComposedArrays:
    """The arrays of a composed set whose triangles index `points`

    normals, colors -- one per point where the matching `..._per_vertex` is
        true, one per triangle where it is false; None for none. A colour has
        three components or four.
    texcoords -- the texture coordinate sets in order (TEXCOORD_0, _1, ...),
        one coordinate per point each
    tangents -- one per point (x, y, z and the bitangent's sign), or None
    crease_angle -- for normals generated per point: the fold, in radians,
        below which they are smoothed across (:func:`crease_normals`); None
        smooths across every fold
    vertex_attributes -- X3D's `attrib` nodes as
        :func:`~OpenGLContext.scenegraph.x3dglsl.vertex_attributes` gives
        them, one row per point

    The points stay shared, and `indices` names them, where every attribute
    is one per point; where one is per triangle, every corner gets its own
    vertex and `indices` is None.
    """
    points = np.ascontiguousarray(points, dtype=np.float32).reshape(-1, 3)
    triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    count = len(points)
    valid = ((triangles >= 0) & (triangles < count)).all(axis=1)
    kept = triangles[valid]
    if not ccw:
        kept = kept[:, [0, 2, 1]]
    short: "list[str]" = []

    def per_vertex(values: Any, name: str, width: int = 0) -> Optional[np.ndarray]:
        if values is None or not len(values):
            return None
        array = np.asarray(values, dtype=np.float32)
        array = array.reshape(len(array), -1) if width == 0 else array.reshape(-1, width)
        if len(array) < count:
            short.append(name)
            return None
        return array[:count]

    def per_face(values: Any, name: str) -> Optional[np.ndarray]:
        if values is None or not len(values):
            return None
        array = np.asarray(values, dtype=np.float32)
        array = array.reshape(len(array), -1)
        if len(array) < len(triangles):
            short.append(name)
            return None
        return array[:len(triangles)][valid]

    given_normals = per_vertex(normals, 'normal', 3) if normal_per_vertex else None
    face_normals = per_face(normals, 'normal') if not normal_per_vertex else None
    vertex_colors = per_vertex(colors, 'color') if color_per_vertex else None
    face_colors = per_face(colors, 'color') if not color_per_vertex else None
    coordinate_sets = [per_vertex(values, 'texCoord', 2) for values in texcoords]
    vertex_tangents = per_vertex(tangents, 'tangent', 4)
    attributes: "dict[str, np.ndarray]" = {}
    creased = (normals is None and normal_per_vertex and crease_angle is not None
               and float(crease_angle) < np.pi)
    if face_colors is None and normal_per_vertex and not creased:
        attributes['POSITION'] = points
        attributes['NORMAL'] = (given_normals if given_normals is not None
                                else vertex_normals(points, kept))
        if vertex_colors is not None:
            attributes['COLOR_0'] = vertex_colors
        if vertex_tangents is not None:
            attributes['TANGENT'] = vertex_tangents
        indices: Optional[np.ndarray] = np.ascontiguousarray(kept.ravel(), dtype=np.uint32)
        corners = None
    else:
        corners = kept.ravel()
        attributes['POSITION'] = points[corners]
        if given_normals is not None:
            attributes['NORMAL'] = given_normals[corners]
        elif face_normals is not None:
            attributes['NORMAL'] = np.repeat(face_normals, 3, axis=0)
        elif creased:
            attributes['NORMAL'] = crease_normals(points, kept, float(crease_angle or 0.0))
        elif normal_per_vertex:
            attributes['NORMAL'] = vertex_normals(points, kept)[corners]
        else:
            attributes['NORMAL'] = np.repeat(_face_normals(points, kept), 3, axis=0)
        if vertex_colors is not None:
            attributes['COLOR_0'] = vertex_colors[corners]
        elif face_colors is not None:
            attributes['COLOR_0'] = np.repeat(face_colors, 3, axis=0)
        if vertex_tangents is not None:
            attributes['TANGENT'] = vertex_tangents[corners]
        indices = None
    for number, values in enumerate(coordinate_sets):
        if values is not None:
            attributes['TEXCOORD_%d' % number] = values if corners is None else values[corners]
    named, missing = x3dglsl.per_vertex(
        vertex_attributes, np.arange(count) if corners is None else corners)
    short.extend(missing)
    return ComposedArrays(
        attributes={name: np.ascontiguousarray(value, dtype=np.float32)
                    for name, value in attributes.items()},
        indices=indices, dropped=int((~valid).sum()), short=short,
        vertex_attributes=named)
