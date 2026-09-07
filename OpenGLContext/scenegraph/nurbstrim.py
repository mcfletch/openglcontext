"""2D trimming primitives for NURBS surfaces.

A trimming contour is a closed loop drawn in a surface's parameter square; what
lies to its left is kept and what lies to its right is cut away, so a
counter-clockwise loop is a boundary and a clockwise loop inside it is a hole.
:class:`Contour2D` joins its children end to end into one such loop, and each
child contributes the points along its own piece of it: a straight run for
:class:`Polyline2D`, an evaluated curve for :class:`NurbsCurve2D`.

:mod:`OpenGLContext.scenegraph.nurbstess` triangulates the region the loops
bound and evaluates the surface at the vertices that come out; :mod:`nurbs`
re-exports these classes, so the ``nurbs.Polyline2D`` / ``nurbs.Contour2D`` node
registrations resolve.

The coordinates are ``(v, u)``, in the surface's own knot ranges -- see the
parameter conventions in :mod:`OpenGLContext.scenegraph.nurbstess`.
"""

from typing import Any

import numpy as np
from opengl_extrusions.nurbs import curve_points
from vrml.vrml97 import nurbs


class Polyline2D(nurbs.Polyline2D):
    """A straight-sided piece of a trimming contour."""

    def points(self, steps: int = 0) -> np.ndarray:
        """The polyline's own points, ``(N, 2)``.

        ``steps`` is accepted so every contour child answers alike; a polyline
        is already as finely divided as it is going to be.
        """
        return np.asarray(self.point, dtype=np.float64).reshape(-1, 2)


class NurbsCurve2D(nurbs.NurbsCurve2D):
    """A curved piece of a trimming contour, evaluated to points.

    ``tessellation`` names how many points to evaluate it at; left at 0 it takes
    :data:`~OpenGLContext.scenegraph.nurbstess.TRIM_CURVE_STEPS`.
    """

    def points(self, steps: int = 0) -> np.ndarray:
        """``(N, 2)`` points along the curve, at even parameter spacing."""
        from OpenGLContext.scenegraph.nurbstess import TRIM_CURVE_STEPS

        control = np.asarray(self.controlPoint, dtype=np.float64).reshape(-1, 2)
        knot = np.asarray(self.knot, dtype=np.float64).ravel()
        if len(control) < 2 or len(knot) < 2:
            return np.zeros((0, 2), dtype=np.float64)
        degree = len(knot) - len(control) - 1
        if degree < 1:
            return control
        count = int(self.tessellation) or steps or TRIM_CURVE_STEPS
        ts = np.linspace(knot[degree], knot[len(control)], max(2, count))
        weight = np.asarray(self.weight, dtype=np.float64).ravel()
        weights = weight if weight.size == len(control) else None
        return curve_points(control, knot, degree, ts, weights=weights)


class Contour2D(nurbs.Contour2D):
    """A closed trimming loop, built from joined polylines and curves.

    children -- the polylines and/or curves which join to form the loop
    """

    def contour(self, steps: int = 0) -> np.ndarray:
        """The whole loop as ``(N, 2)`` points, children joined in order.

        Where one child ends on the point the next begins with, the point is
        kept once; the loop closes from the last point back to the first, so a
        contour that repeats its start at the end is no different from one that
        does not.
        """
        pieces = []
        for child in self.children:
            points = getattr(child, 'points', None)
            if points is None:
                continue
            piece = np.asarray(points(steps), dtype=np.float64).reshape(-1, 2)
            if not len(piece):
                continue
            if pieces and np.allclose(pieces[-1][-1], piece[0]):
                piece = piece[1:]
            if len(piece):
                pieces.append(piece)
        if not pieces:
            return np.zeros((0, 2), dtype=np.float64)
        loop = np.concatenate(pieces)
        if len(loop) > 1 and np.allclose(loop[0], loop[-1]):
            loop = loop[:-1]
        return loop
