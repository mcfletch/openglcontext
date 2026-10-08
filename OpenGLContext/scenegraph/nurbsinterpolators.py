"""X3D's NURBS interpolators: a position, an orientation or a surface point for each fraction -- no GL

Each takes a fraction as the other interpolators do (`set_fraction`), runs
it from 0 to 1 across its curve's or surface's domain, and sends what is
there (ISO/IEC 19775-1, 27.4):

- `NurbsPositionInterpolator` - the point on its curve, as `value_changed`.
- `NurbsOrientationInterpolator` - the rotation turning +z to the curve's
  direction there, as `value_changed`.
- `NurbsSurfaceInterpolator` - for a (u, v) fraction, the point on its
  surface as `position_changed` and the unit normal (∂p/∂u × ∂p/∂v) as
  `normal_changed`.

The curve or surface is :mod:`~OpenGLContext.scenegraph.nurbseval`'s, kept
in vrml's cache until a field of the node or of its control points is set.
A node whose fields describe no curve or surface sends nothing.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Optional

import numpy as np
from vrml import cache
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import nurbseval
from OpenGLContext.scenegraph.nurbsx3d import depend_on_sources, control_points

__all__ = ['NurbsOrientationInterpolator', 'NurbsPositionInterpolator',
           'NurbsSurfaceInterpolator', 'rotation_to']

#: The key the evaluated curve or surface is kept under in vrml's cache.
EVALUATOR_KEY = 'nurbs-evaluator'


def _held(node: Any, make: Callable[[], Any]) -> Any:
    """`make()`, kept until a field of `node` or of its control points is set"""
    held = cache.CACHE.getData(node, EVALUATOR_KEY)
    if held is None:
        held = (make(),)
        sources = [node] + ([node.controlPoint] if node.controlPoint else [])
        depend_on_sources(cache.CACHE.holder(node, held, EVALUATOR_KEY), iter(sources))
    return held[0]


def rotation_to(direction: Any) -> np.ndarray:
    """The X3D rotation (axis, angle) turning +z to `direction`"""
    found = np.asarray(direction, dtype=np.float64)
    length = float(np.linalg.norm(found))
    if not length or not math.isfinite(length):
        return np.array([0.0, 0.0, 1.0, 0.0])
    found = found / length
    axis = np.cross((0.0, 0.0, 1.0), found)
    sine = float(np.linalg.norm(axis))
    cosine = float(found[2])
    if sine < 1e-12:
        return np.array([0.0, 0.0, 1.0, 0.0]) if cosine > 0 else np.array([1.0, 0.0, 0.0, math.pi])
    return np.concatenate([axis / sine, [math.atan2(sine, cosine)]])


class _CurveInterpolator:
    """An interpolator along the curve its fields describe"""

    controlPoint: Any
    knot: Any
    order: Any
    weight: Any
    value_changed: Any

    def curve(self) -> Optional[nurbseval.Curve]:
        """The curve, or None where the fields describe none"""
        def make() -> Optional[nurbseval.Curve]:
            points = control_points(self.controlPoint)
            return None if points is None else nurbseval.curve(points, self.knot, self.order,
                                                               self.weight)
        found: Optional[nurbseval.Curve] = _held(self, make)
        return found

    def evaluate(self, curve: nurbseval.Curve, fraction: float) -> Any:
        raise NotImplementedError('%s must evaluate its curve' % type(self).__name__)

    def on_set_fraction(self, value: Any) -> Any:
        """Send the value at fraction `value`, and return it; None with no curve"""
        found = self.curve()
        if found is None:
            return None
        self.value_changed = self.evaluate(found, float(value))
        return self.value_changed


class NurbsPositionInterpolator(_CurveInterpolator, x3d.NurbsPositionInterpolator):
    """The point a fraction of the way along a NURBS curve"""

    def evaluate(self, curve: nurbseval.Curve, fraction: float) -> Any:
        return curve.at([fraction])[0]


class NurbsOrientationInterpolator(_CurveInterpolator, x3d.NurbsOrientationInterpolator):
    """The rotation turning +z to a NURBS curve's direction a fraction of the way along it"""

    def evaluate(self, curve: nurbseval.Curve, fraction: float) -> Any:
        return rotation_to(curve.tangent_at([fraction])[0])


class NurbsSurfaceInterpolator(x3d.NurbsSurfaceInterpolator):
    """The point and normal at a (u, v) fraction of a NURBS surface"""

    def surface(self) -> Optional[nurbseval.Surface]:
        """The surface, or None where the fields describe none"""
        def make() -> Optional[nurbseval.Surface]:
            points = control_points(self.controlPoint)
            return None if points is None else nurbseval.surface(
                points, self.uDimension, self.vDimension, self.uKnot, self.vKnot,
                self.uOrder, self.vOrder, self.weight)
        found: Optional[nurbseval.Surface] = _held(self, make)
        return found

    def on_set_fraction(self, value: Any) -> Any:
        """Send the position and normal at (u, v) fraction `value`; None with no surface"""
        found = self.surface()
        if found is None:
            return None
        positions, normals = found.at([tuple(np.asarray(value, dtype=np.float64)[:2])])
        self.normal_changed = normals[0]
        self.position_changed = positions[0]
        return self.position_changed
