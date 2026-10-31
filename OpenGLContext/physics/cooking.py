"""Collision shapes cooked from triangles: hulls, convex pieces and their volumes.

:meth:`Proxy.from_mesh <OpenGLContext.physics.proxy.Proxy.from_mesh>` hands its
``convex``, ``trimesh`` and ``auto`` strategies here (:func:`cook`). A static
body with triangles keeps them; otherwise a mesh is its convex hull, or a
compound of convex pieces where the hull fills less than 60% of the points'
bounding box (:func:`concavity` over 0.4).

The hull is an incremental 3D hull with no SciPy dependency. The decomposition
splits a cloud at the median of its widest axis, at most three levels deep and
eight pieces, until each piece's concavity is under 0.3. Both run in NumPy on
the calling thread; the service cooks scenery on a worker thread.

The hull and decomposition are those of omi_physics' ``hull`` and ``cookery``
modules (MIT, Mike C. Fletcher), so an engine and the omi engine cook a mesh
into the same pieces.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.physics.proxy import Proxy

__all__ = ['EPS', 'approximate_convex_decomposition', 'concavity', 'convex_hull', 'cook',
           'hull_volume', 'points_hull_volume']

#: Below this a length, an area or a distance from a plane is zero.
EPS = 1e-9

_Face = tuple[int, int, int]


def convex_hull(points: Any) -> tuple[np.ndarray, np.ndarray]:
    """The hull of ``points``: its vertices ``(V, 3)`` and outward triangles ``(F, 3)``.

    Fewer than four points, or points with no volume between them, give the
    unique points and no triangles.
    """
    pts = np.unique(np.asarray(points, dtype='d').reshape(-1, 3), axis=0)
    if len(pts) < 4:
        return pts, np.zeros((0, 3), dtype='i')
    tetra = _initial_tetra(pts)
    if tetra is None:
        return pts, np.zeros((0, 3), dtype='i')
    faces = _incremental(pts, tetra)
    used = np.unique(np.asarray(faces).ravel())
    remap = {int(old): new for new, old in enumerate(used)}
    return pts[used], np.array([[remap[i] for i in face] for face in faces], dtype='i')


def _initial_tetra(pts: np.ndarray) -> list[_Face] | None:
    """Four outward faces of a tetrahedron of the points with volume, or None."""
    i0 = 0
    i1 = int(np.argmax(np.linalg.norm(pts - pts[i0], axis=1)))
    if np.linalg.norm(pts[i1] - pts[i0]) < EPS:
        return None
    areas = np.linalg.norm(np.cross(pts - pts[i0], pts[i1] - pts[i0]), axis=1)
    i2 = int(np.argmax(areas))
    if areas[i2] < EPS:
        return None
    normal = np.cross(pts[i1] - pts[i0], pts[i2] - pts[i0])
    distances = np.abs((pts - pts[i0]) @ normal)
    i3 = int(np.argmax(distances))
    if distances[i3] < EPS:
        return None
    corners = [i0, i1, i2, i3]
    if np.dot(normal, pts[i3] - pts[i0]) > 0:
        corners[1], corners[2] = corners[2], corners[1]
    a, b, c, d = corners
    return [(a, b, c), (a, c, d), (a, d, b), (b, d, c)]


def _incremental(pts: np.ndarray, faces: list[_Face]) -> list[_Face]:
    """Each point added to the hull, the faces it sees replaced by faces to it.

    The seed corners are on the hull already and are not added again: a face
    built nearly coplanar with a seed face can leave a corner within rounding
    above it, and adding that corner again folds the surface.
    """
    faces = list(faces)
    seeds = {i for face in faces for i in face}
    for p in range(len(pts)):
        if p in seeds:
            continue
        point = pts[p]
        visible = [face for face in faces if np.dot(*_plane_offset(pts, face, point)) > EPS]
        if not visible:
            continue
        horizon = _horizon(visible)
        faces = [face for face in faces if face not in visible]
        faces.extend((i, j, p) for i, j in horizon)
    return faces


def _plane_offset(pts: np.ndarray, face: _Face, point: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A face's unit normal, and ``point`` relative to the face's first corner."""
    a, b, c = pts[face[0]], pts[face[1]], pts[face[2]]
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal)
    if length > EPS:
        normal = normal / length
    return normal, point - a


def _horizon(visible: list[_Face]) -> list[tuple[int, int]]:
    """The edges of the visible faces that belong to one of them only, in their winding."""
    counts: dict[tuple[int, int], int] = {}
    for face in visible:
        for i, j in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (min(i, j), max(i, j))
            counts[key] = counts.get(key, 0) + 1
    return [(i, j) for face in visible
            for i, j in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))
            if counts[(min(i, j), max(i, j))] == 1]


def hull_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """The volume a triangulated hull encloses, in cubic metres; 0 for no triangles."""
    if len(faces) == 0:
        return 0.0
    centre = vertices.mean(axis=0)
    a = vertices[faces[:, 0]] - centre
    b = vertices[faces[:, 1]] - centre
    c = vertices[faces[:, 2]] - centre
    return float(np.abs(np.einsum('ij,ij->i', a, np.cross(b, c))).sum() / 6.0)


def points_hull_volume(points: np.ndarray) -> float:
    """The volume of the hull of ``points``; their bounding box, at least 1e-6 a side, where they have no hull."""
    vertices, faces = convex_hull(points)
    if len(faces) == 0:
        return float(np.prod(np.maximum(points.max(axis=0) - points.min(axis=0), 1e-6)))
    return hull_volume(vertices, faces)


def concavity(points: Any) -> float:
    """One less the share of its bounding box the points' hull fills, 0 to 1: higher is more concave."""
    pts = np.asarray(points, dtype='d')
    vertices, faces = convex_hull(pts)
    if len(faces) == 0:
        return 0.0
    box = float(np.prod(np.maximum(pts.max(axis=0) - pts.min(axis=0), EPS)))
    return float(np.clip(1.0 - hull_volume(vertices, faces) / box, 0.0, 1.0))


def approximate_convex_decomposition(points: Any, max_pieces: int = 8, threshold: float = 0.30,
                                     depth: int = 0) -> list[np.ndarray]:
    """The points split into pieces each nearly convex, as point arrays.

    A cloud is split at the median of its widest axis until a piece's
    :func:`concavity` is under ``threshold``, it holds 8 points or fewer, the
    split is three levels deep, or ``max_pieces`` is spent.
    """
    pts = np.asarray(points, dtype='d')
    if depth >= 3 or max_pieces <= 1 or len(pts) <= 8 or concavity(pts) < threshold:
        return [pts]
    axis = int(np.argmax(pts.max(axis=0) - pts.min(axis=0)))
    middle = np.median(pts[:, axis])
    left, right = pts[pts[:, axis] <= middle], pts[pts[:, axis] > middle]
    if len(left) < 4 or len(right) < 4:
        return [pts]
    budget = max_pieces // 2
    return (approximate_convex_decomposition(left, budget, threshold, depth + 1)
            + approximate_convex_decomposition(right, budget, threshold, depth + 1))


def _convex(points: np.ndarray) -> Proxy:
    """A ``convex`` proxy of the points' hull, or of the points where they have no hull."""
    from OpenGLContext.physics.proxy import Proxy  # noqa: PLC0415 proxy cooks through this module

    vertices, _faces = convex_hull(points)
    return Proxy.convex(vertices if len(vertices) >= 4 else points)


def cook(points: np.ndarray, indices: np.ndarray | None, strategy: str, dynamic: bool) -> Proxy:
    """A proxy cooked from triangles: their hull, the triangles, or convex pieces of them.

    ``strategy`` ``'convex'`` is the hull. Any other is ``auto``: a static body
    with ``indices`` keeps its triangles, and otherwise the points are the hull,
    or convex pieces where :func:`concavity` is over 0.4.
    """
    from OpenGLContext.physics.proxy import Proxy  # noqa: PLC0415 proxy cooks through this module

    pts = np.asarray(points, dtype='d')
    if strategy != 'convex':
        if not dynamic and indices is not None:
            return Proxy.trimesh(pts, np.asarray(indices, dtype='i'))
        if concavity(pts) > 0.4:
            pieces = approximate_convex_decomposition(pts)
            return Proxy('compound', {'parts': tuple(
                (_convex(piece), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)) for piece in pieces)})
    return _convex(pts)
