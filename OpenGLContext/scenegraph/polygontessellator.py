"""Triangles from polygons of vertices, for IndexedFaceSets, Polygons and glyphs.

A polygon is one or more closed contours of
:class:`~OpenGLContext.scenegraph.vertex.Vertex` objects in 3D.  The contours
are projected onto their plane and triangulated by
:func:`opengl_extrusions.tessellate`, a constrained Delaunay triangulation
that takes holes, crossings and either winding.  The triangles are made of the
vertices given, so each keeps its colour, normal and texture coordinate; where
two edges cross, a vertex is made between the ends of one of them.  No GL
context and no GLU library is involved.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Optional, Union

import numpy as np
from OpenGL.GL import GL_TRIANGLES
from OpenGL.constant import Constant
from OpenGL.raw.GLU.constants import (
    GLU_TESS_WINDING_ABS_GEQ_TWO,
    GLU_TESS_WINDING_NEGATIVE,
    GLU_TESS_WINDING_NONZERO,
    GLU_TESS_WINDING_ODD,
    GLU_TESS_WINDING_POSITIVE,
)
from opengl_extrusions import tessellate as triangulate
from opengl_extrusions.cdt import WINDING_RULES as _INSIDE

from OpenGLContext import utilities
from OpenGLContext.scenegraph.vertex import Vertex

__all__ = ['PolygonTessellator', 'WINDING_RULES']

#: GLU's winding-rule constants, by the name :mod:`opengl_extrusions` gives
#: the same rule.
WINDING_RULES: dict[Union[int, Constant], str] = {
    GLU_TESS_WINDING_ODD: 'odd',
    GLU_TESS_WINDING_NONZERO: 'nonzero',
    GLU_TESS_WINDING_POSITIVE: 'positive',
    GLU_TESS_WINDING_NEGATIVE: 'negative',
    GLU_TESS_WINDING_ABS_GEQ_TWO: 'abs_geq_two',
}

#: A normal shorter than this fraction of the polygon's squared extent is no
#: normal: the contours' areas cancel, or every point is on one line.
_FLAT = 1e-12


class PolygonTessellator(object):
    """Triangulates polygons given as contours of vertices.

    windingRule -- which regions of overlapping contours are inside: a
        ``GLU_TESS_WINDING_*`` constant, or the name of one of
        :data:`opengl_extrusions.cdt.WINDING_RULES` (``'odd'``,
        ``'nonzero'``, ``'positive'``, ``'negative'``, ``'abs_geq_two'``)
    ccw -- False reverses every triangle, for faces meant to wind clockwise

    A tessellator holds no state between calls, so one may be shared.
    """

    def __init__(self, windingRule: Union[int, str, Constant] = GLU_TESS_WINDING_ODD,
                 ccw: bool = True) -> None:
        self.windingRule = windingRule
        self.ccw = ccw

    @property
    def winding(self) -> str:
        """The winding rule, by its :mod:`opengl_extrusions` name."""
        rule = self.windingRule
        return rule if isinstance(rule, str) else WINDING_RULES[rule]

    def tessContours(self, contours: Sequence[Sequence[Vertex]],
                     forceTriangles: int = 1, normal: Any = None) -> list[Any]:
        """Triangulate the polygon the contours outline.

        contours -- sequences of vertices, each a closed contour; a contour
            inside another is a hole or an island as the winding rule says
        forceTriangles -- if true (the default), the result is a flat list of
            vertices, three to a triangle; if false, it is a list of
            ``(GL_TRIANGLES, vertices)`` primitives, empty for no triangles
        normal -- the direction the triangles face, counter-clockwise about
            it.  None, or a zero vector, takes the normal the contours define:
            a single contour's triangles then wind as the contour does.

        A polygon with no area, or a coordinate that is not finite, has no
        triangles.
        """
        rings = [list(contour) for contour in contours if len(contour)]
        triangles = self._convex_fan(rings[0], normal) if len(rings) == 1 else None
        if triangles is None:
            triangles = self._triangles(rings, normal)
        if forceTriangles:
            return triangles
        return [(GL_TRIANGLES, triangles)] if triangles else []

    def tessellate(self, vertices: Sequence[Vertex],
                   forceTriangles: int = 1) -> list[Any]:
        """Triangulate one contour; :meth:`tessContours` of ``[vertices]``."""
        return self.tessContours([vertices], forceTriangles=forceTriangles)

    def combine(self, newPosition: Any, vertices: Sequence[Optional[Vertex]],
                weights: Sequence[float]) -> Vertex:
        """A vertex at newPosition, its attributes the weighted sum of vertices'

        The colour and texture coordinate are the weighted sums of those the
        vertices have; the normal is their weighted combination, normalised.
        """
        pairs = [(vertex, float(weight))
                 for vertex, weight in zip(vertices, weights) if vertex is not None]
        attributes: dict[str, Any] = {'point': newPosition}
        for name in ('color', 'textureCoordinate'):
            values = [(np.asarray(getattr(vertex, name), 'f'), weight)
                      for vertex, weight in pairs
                      if getattr(vertex, name, None) is not None]
            attributes[name] = (
                sum((value * weight for value, weight in values), np.zeros_like(values[0][0]))
                if values else None)
        normals = [(vertex.normal, weight) for vertex, weight in pairs
                   if getattr(vertex, 'normal', None) is not None]
        if len(normals) == 1:
            attributes['normal'] = normals[0][0]
        elif normals:
            attributes['normal'] = utilities.combineNormals(
                [value for value, _ in normals], [weight for _, weight in normals])
        return Vertex(**attributes)

    def _convex_fan(self, ring: list[Vertex], normal: Any) -> Optional[list[Vertex]]:
        """A convex ring's triangles, as a fan from its first vertex.

        None where the ring is not strictly convex in its plane (a reflex or
        straight vertex, two points in one place, an outline that goes round
        more than once, a coordinate that is not finite), for
        :meth:`_triangles` to decide.  Most faces are convex, and this is
        arithmetic on a handful of floats where the general triangulation
        builds a graph.
        """
        count = len(ring)
        if count < 3:
            return None
        ox, oy, oz = (float(c) for c in ring[0].point)
        local = [(float(x) - ox, float(y) - oy, float(z) - oz)
                 for x, y, z in (vertex.point for vertex in ring)]
        nx = ny = nz = 0.0
        if normal is not None:
            nx, ny, nz = (float(c) for c in normal)
        if not (nx or ny or nz):
            for (ax, ay, az), (bx, by, bz) in zip(local, local[1:] + local[:1]):
                nx += ay * bz - az * by
                ny += az * bx - ax * bz
                nz += ax * by - ay * bx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if not (0.0 < length < math.inf):
            return None
        (ux, uy, uz), (vx, vy, vz) = _plane_basis(nx / length, ny / length, nz / length)
        flat = [(x * ux + y * uy + z * uz, x * vx + y * vy + z * vz) for x, y, z in local]
        turned, turning = 0, 0.0
        (ax, ay), (bx, by) = flat[-2], flat[-1]
        for cx, cy in flat:
            ex, ey, fx, fy = bx - ax, by - ay, cx - bx, cy - by
            cross = ex * fy - ey * fx
            if not abs(cross) > 1e-9 * math.hypot(ex, ey) * math.hypot(fx, fy):
                return None
            way = 1 if cross > 0 else -1
            if turned and way != turned:
                return None
            turned = way
            turning += math.atan2(cross, ex * fx + ey * fy)
            (ax, ay), (bx, by) = (bx, by), (cx, cy)
        if abs(turning) > 3 * math.pi:
            return None
        if not _INSIDE[self.winding](turned):
            return []
        first = ring[0]
        if (turned > 0) == self.ccw:
            return [vertex for i in range(1, count - 1)
                    for vertex in (first, ring[i], ring[i + 1])]
        return [vertex for i in range(1, count - 1)
                for vertex in (first, ring[i + 1], ring[i])]

    def _triangles(self, rings: list[list[Vertex]], normal: Any) -> list[Vertex]:
        """The vertices of the rings' triangles, three to a triangle."""
        if not rings:
            return []
        given = [vertex for ring in rings for vertex in ring]
        points = np.array([vertex.point for vertex in given], dtype='d')
        if not np.isfinite(points).all():
            return []
        bounds = np.cumsum([0] + [len(ring) for ring in rings])
        local = points - points[0]
        axis = _unit(normal) if normal is not None else None
        if axis is None:
            axis = _contour_normal(local, bounds)
        if axis is None:
            return []
        plane = local @ np.array(_plane_basis(*axis.tolist())).T
        found = triangulate(
            [plane[start:end] for start, end in zip(bounds[:-1], bounds[1:])],
            winding=self.winding)
        indices = found.triangles if self.ccw else found.triangles[:, ::-1]
        made: dict[int, Vertex] = {}
        result = []
        for index in indices.ravel().tolist():
            source = int(found.source_index[index])
            if source >= 0:
                result.append(given[source])
                continue
            vertex = made.get(index)
            if vertex is None:
                vertex = made[index] = self._crossing(
                    found.points[index], plane, bounds, given)
            result.append(vertex)
        return result

    def _crossing(self, at: np.ndarray, plane: np.ndarray, bounds: np.ndarray,
                  given: list[Vertex]) -> Vertex:
        """A vertex where two edges cross, blended along the nearer of them."""
        starts = np.arange(len(given))
        ends = starts + 1
        ends[bounds[1:] - 1] = bounds[:-1]
        a, b = plane[starts], plane[ends]
        along = b - a
        length = np.einsum('ij,ij->i', along, along)
        t = np.clip(np.einsum('ij,ij->i', at - a, along) / np.where(length > 0, length, 1.0),
                    0.0, 1.0)
        nearest = int(np.argmin(np.linalg.norm(a + along * t[:, None] - at, axis=1)))
        weight = float(t[nearest])
        first, second = given[starts[nearest]], given[ends[nearest]]
        return self.combine(
            first.point * (1.0 - weight) + second.point * weight,
            [first, second], [1.0 - weight, weight])


def _unit(vector: Any) -> Optional[np.ndarray]:
    """``vector`` normalised, or None for a zero or non-finite one."""
    vector = np.asarray(vector, dtype='d').reshape(3)
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length == 0.0:
        return None
    unit: np.ndarray = vector / length
    return unit


def _contour_normal(points: np.ndarray, bounds: np.ndarray) -> Optional[np.ndarray]:
    """The unit normal about which the contours wind counter-clockwise.

    Newell's normal, the contours' summed area vector.  Where their areas
    cancel (a bow tie) it is the normal of the largest triangle of points,
    and where that has no area either, the points are on a line: None.
    """
    extent = float(np.ptp(points, axis=0).max())
    if extent == 0.0:
        return None
    total = np.zeros(3)
    for start, end in zip(bounds[:-1], bounds[1:]):
        ring = points[start:end]
        total += np.cross(ring, np.roll(ring, -1, axis=0)).sum(axis=0)
    if np.linalg.norm(total) > _FLAT * extent * extent:
        return _unit(total)
    far = points[int(np.argmax(np.linalg.norm(points, axis=1)))]
    crosses = np.cross(far, points)
    widest = crosses[int(np.argmax(np.linalg.norm(crosses, axis=1)))]
    if np.linalg.norm(widest) <= _FLAT * extent * extent:
        return None
    return _unit(widest)


def _plane_basis(nx: float, ny: float, nz: float) -> tuple[
        tuple[float, float, float], tuple[float, float, float]]:
    """Unit vectors u, v across the plane of the unit normal n, with u x v = n.

    u is n crossed into the axis it is least along, so it is never short.
    """
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if ax <= ay and ax <= az:
        ux, uy, uz = 0.0, -nz, ny
    elif ay <= az:
        ux, uy, uz = nz, 0.0, -nx
    else:
        ux, uy, uz = -ny, nx, 0.0
    length = math.sqrt(ux * ux + uy * uy + uz * uz)
    ux, uy, uz = ux / length, uy / length, uz / length
    return (ux, uy, uz), (ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux)
