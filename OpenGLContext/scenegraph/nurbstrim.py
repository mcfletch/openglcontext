"""2D trimming primitives for NURBS surfaces.

Each is a thin wrapper over a GLU trim call; a :class:`Contour2D` groups children
between ``gluBeginTrim``/``gluEndTrim``. :mod:`nurbs` re-exports these, so the
``nurbs.Polyline2D`` / ``nurbs.Contour2D`` node registrations resolve.
"""

from typing import Any

from vrml.vrml97 import nurbs
from OpenGL.GLU import (
    GLU_MAP1_TRIM_2, gluBeginTrim, gluEndTrim, gluNurbsCurve, gluPwlCurve,
)


class Polyline2D(nurbs.Polyline2D):
    """Simple polyline in 2D

    Basically this just calls gluPwlCurve
    """

    def render(self, nurbObject: Any) -> None:
        """Render to the given nurbs object"""
        gluPwlCurve(nurbObject, self.point, GLU_MAP1_TRIM_2)


class NurbsCurve2D(nurbs.NurbsCurve2D):
    """Nurbs curve in 2D

    Basically this just calls gluNurbsCurve
    """

    def render(self, nurbObject: Any) -> None:
        """Render to the given nurbs object"""
        gluNurbsCurve(nurbObject, self.knot, self.controlPoint, GLU_MAP1_TRIM_2)


class Contour2D(nurbs.Contour2D):
    """A 2D contour (collection of joined segments)

    children -- a set of polylines and/or curves which are
        joined to form the trimming contour

    Normally used to trim a Nurbs surface...
    """

    def trim(self, nurbObject: Any) -> None:
        """Render the contour as a trim of the current surface"""
        gluBeginTrim(nurbObject)
        try:
            for child in self.children:
                child.render(nurbObject)
        finally:
            gluEndTrim(nurbObject)
