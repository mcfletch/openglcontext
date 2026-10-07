"""X3D's Geometry2D component: flat shapes in the z=0 plane

`Rectangle2D`, `TriangleSet2D`, `Disk2D` and `ArcClose2D` are drawn as the
mesh their fields build, facing +z (:class:`~OpenGLContext.scenegraph.meshgeometry.MeshDrawn`),
with texture coordinates across their bounds; `Circle2D`, `Arc2D` and
`Polyline2D` as the engine's `IndexedLineSet`, and `Polypoint2D` as its
`PointSet` (:class:`~OpenGLContext.scenegraph.meshgeometry.DrawnAs`). A
curve has :data:`SEGMENTS` segments to a whole turn. The arithmetic is
:mod:`~OpenGLContext.scenegraph.composedgeometry`'s.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import composedgeometry as cg
from OpenGLContext.scenegraph.meshgeometry import DrawnAs, MeshDrawn, polylines

__all__ = ['Arc2D', 'ArcClose2D', 'Circle2D', 'Disk2D', 'Polyline2D', 'Polypoint2D',
           'Rectangle2D', 'SEGMENTS', 'TriangleSet2D']

#: Segments to a whole turn of a curve.
SEGMENTS = 48


def _segments(sweep: float) -> int:
    """Segments for an arc turning `sweep` radians"""
    return max(int(math.ceil(SEGMENTS * sweep / (2.0 * math.pi))), 2)


class _FlatMesh(MeshDrawn):
    """A flat shape drawn as a mesh: a subclass gives its points, triangles and coordinates"""

    solid: Any

    def flat(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        """Points, triangles and texture coordinates of the shape"""
        raise NotImplementedError('%s must give its shape' % type(self).__name__)

    def buildMesh(self) -> Optional[Any]:
        """The shape's mesh, or None for one with no triangles"""
        points, triangles, texcoords = self.flat()
        if not len(triangles):
            return None
        return self.meshFrom(cg.composed_arrays(points, triangles, texcoords=[texcoords]),
                             solid=bool(self.solid))


class Rectangle2D(_FlatMesh, x3d.Rectangle2D):
    """A rectangle of `size`, centred on the origin"""

    def flat(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        return cg.rectangle(self.size)


class TriangleSet2D(_FlatMesh, x3d.TriangleSet2D):
    """Triangles of `vertices` taken three at a time"""

    def flat(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        return cg.triangle_set_2d(self.vertices)


class Disk2D(_FlatMesh, x3d.Disk2D):
    """A disk of `outerRadius`, with a hole of `innerRadius` where that is above 0"""

    def flat(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        return cg.disk(float(self.innerRadius), float(self.outerRadius), SEGMENTS)


class ArcClose2D(_FlatMesh, x3d.ArcClose2D):
    """An arc closed through its centre ('PIE') or across its ends ('CHORD')"""

    def flat(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        sweep = cg.arc_sweep(self.startAngle, self.endAngle)
        return cg.arc_close(float(self.radius), float(self.startAngle), float(self.endAngle),
                            str(self.closureType), _segments(sweep))


class Circle2D(DrawnAs, x3d.Circle2D):
    """A circle of `radius`, as a line"""

    def buildDrawn(self) -> Any:
        points = cg.arc_points(float(self.radius), 0.0, 2.0 * math.pi, SEGMENTS)
        return polylines(points, [len(points)])


class Arc2D(DrawnAs, x3d.Arc2D):
    """An arc of `radius` from `startAngle` counter-clockwise to `endAngle`, as a line"""

    def buildDrawn(self) -> Any:
        sweep = cg.arc_sweep(self.startAngle, self.endAngle)
        points = cg.arc_points(float(self.radius), float(self.startAngle),
                               float(self.endAngle), _segments(sweep))
        return polylines(points, [len(points)])


class Polyline2D(DrawnAs, x3d.Polyline2D):
    """A line through `lineSegments`"""

    def buildDrawn(self) -> Any:
        flat = np.asarray(self.lineSegments, np.float32).reshape(-1, 2)
        points = np.concatenate([flat, np.zeros((len(flat), 1), np.float32)], axis=1)
        return polylines(points, [len(points)])


class Polypoint2D(DrawnAs, x3d.Polypoint2D):
    """The points of `point`, as the engine's PointSet"""

    def buildDrawn(self) -> Any:
        from OpenGLContext.scenegraph.basenodes import PointSet  # noqa: PLC0415 imports GL
        flat = np.asarray(self.point, np.float32).reshape(-1, 2)
        points = np.concatenate([flat, np.zeros((len(flat), 1), np.float32)], axis=1)
        return PointSet(coord=x3d.Coordinate(point=points))
