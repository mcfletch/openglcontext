"""X3D's NURBS fields as curves, surfaces and triangles -- NumPy only, no GL

The X3D NURBS nodes (ISO/IEC 19775-1, 27) describe a curve or a surface by
control points, an order and a knot vector per parametric direction, and
optionally a weight per control point. This module applies the rules the
specification gives those fields and evaluates the result with
:mod:`opengl_extrusions.nurbs`:

- :func:`knot_vector` - the node's knots where they are a knot vector for its
  order and control points, and a uniform one otherwise: clamped, or periodic
  for a closed direction.
- :func:`weights` - one positive weight per control point, or none.
- :func:`segments` - how many segments a direction is tessellated into, from
  a `tessellation`/`uTessellation`/`vTessellation` field: a positive value is
  the count, a negative one is that many per control point, and zero is
  :data:`SEGMENTS_PER_SPAN` per knot span (one for a straight direction), but
  never fewer than two per control point.
- :func:`curve` and :func:`surface` - a :class:`Curve` or :class:`Surface`
  from a node's fields, or None for fields that describe none (an order below
  2, fewer control points than the order).
- :meth:`Surface.tessellate` - a :class:`Patch` of points, normals, parameter
  fractions and triangles, trimmed by contours in the surface's own knot range
  under the even-odd rule.
- :func:`swept` and :func:`swung` - the meshes of `NurbsSweptSurface` and
  `NurbsSwungSurface`: a cross-section curve swept along a trajectory curve as
  an `Extrusion` sweeps its cross-section along its spine.

A weighted control point is given multiplied by its weight -- as the
homogeneous point ``(w x, w y, w z, w)`` without its last coordinate -- which
is how the X3D examples write them (a quarter circle's corner point at
``√2/2`` is written ``(√2/2, √2/2)``, not ``(1, 1)``). The points are divided by
their weights before they are evaluated.

A direction is closed where its node asks for it and its first and last rows
of control points coincide, with equal weights; it is then evaluated as a
periodic spline, the first ``order - 2`` rows repeated after the last, so the
seam is as smooth as the rest of the surface.

Control points are u-major in the node (u varies fastest) and are held here
as ``(u, v, components)``, so a surface's normal is ``∂p/∂u × ∂p/∂v`` and its
triangles wind counter-clockwise about it.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from opengl_extrusions import tessellate as tessellate_domain
from opengl_extrusions import vrml97_extrusion
from opengl_extrusions.nurbs import (
    basis_derivatives, basis_functions, curve_points, normals_at, surface_at,
    surface_normals, surface_points,
)

__all__ = ['Curve', 'MAX_SEGMENTS', 'Net', 'Patch', 'SEGMENTS_PER_SPAN', 'Surface', 'TRIM_WINDING',
           'clip_ring', 'curve', 'knot_vector', 'segments', 'surface', 'swept', 'swung',
           'texture_net', 'weights']

#: Segments per knot span of a curved direction whose tessellation field is 0.
SEGMENTS_PER_SPAN = 10

#: The most segments one direction is given, whatever its fields ask for.
MAX_SEGMENTS = 512

#: Which regions of a trimmed domain are kept: inside an odd number of
#: contours, so an outer boundary and the holes inside it may wind either way.
TRIM_WINDING = 'odd'


def knot_vector(knot: Any, order: int, dimension: int, closed: bool = False) -> np.ndarray:
    """The knots a direction of `dimension` control points of `order` is evaluated with

    `knot` is kept where it has ``dimension + order`` values that do not
    decrease and never repeat one value more than `order` times; otherwise the
    knots are uniform over 0..1, clamped (`order` equal knots at each end), or
    for a closed direction evenly spaced throughout. A closed direction's
    vector then runs ``order - 2`` knots further at the spacing it starts with,
    for the control points :func:`curve` and :func:`surface` repeat.
    """
    length = dimension + order
    found = np.asarray(knot, dtype=np.float64).ravel()
    if not _valid_knots(found, order, length):
        if closed:
            found = np.arange(length, dtype=np.float64)
        else:
            inner = np.arange(1, dimension - order + 1, dtype=np.float64)
            found = np.concatenate([np.zeros(order), inner,
                                    np.full(order, dimension - order + 1.0)])
        found = found / found[-1]
    if closed:
        extra = [found[-1]]
        for index in range(1, order - 1):
            extra.append(extra[-1] + (found[index] - found[index - 1]))
        found = np.concatenate([found, extra[1:]])
    return found


def _valid_knots(knots: np.ndarray, order: int, length: int) -> bool:
    if len(knots) != length or not np.isfinite(knots).all():
        return False
    steps = np.diff(knots)
    if (steps < 0).any() or knots[-1] <= knots[0]:
        return False
    run = 1
    for step in steps:
        run = run + 1 if step == 0 else 1
        if run > order:
            return False
    return True


def weights(weight: Any, count: int) -> Optional[np.ndarray]:
    """`weight` where it is one positive, finite weight per control point; None otherwise"""
    found = np.asarray(weight, dtype=np.float64).ravel()
    if found.size != count or not count:
        return None
    if not (np.isfinite(found).all() and (found > 0).all()):
        return None
    return found


def segments(tessellation: int, dimension: int, degree: int, spans: int,
             scale: float = 1.0) -> int:
    """How many segments a direction is tessellated into (see the module docstring)

    `scale` multiplies the count, as a `NurbsSet`'s `tessellationScale` does;
    the result is between 1 and :data:`MAX_SEGMENTS`.
    """
    tessellation = int(tessellation)
    if tessellation > 0:
        count = float(tessellation)
    elif tessellation < 0:
        count = float(-tessellation * dimension)
    elif degree <= 1:
        count = float(max(spans, 1))
    else:
        count = float(max(2 * dimension, SEGMENTS_PER_SPAN * spans))
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    return int(min(MAX_SEGMENTS, max(1, math.floor(count * scale))))


def _spans(knots: np.ndarray, degree: int, count: int) -> int:
    """Knot intervals of non-zero length within the evaluated range"""
    return int((np.diff(knots[degree:count + 1]) > 0).sum())


def _coincide(first: np.ndarray, last: np.ndarray, weight: Optional[np.ndarray],
              first_index: Any, last_index: Any) -> bool:
    """Whether a row of control points ends where it starts, with the same weights"""
    if not np.allclose(first, last, rtol=0.0, atol=1e-9):
        return False
    return weight is None or bool(np.allclose(weight[first_index], weight[last_index]))


@dataclass(frozen=True)
class Curve:
    """A NURBS curve of any number of components, ready to evaluate

    `control` and `weights` already repeat the points a closed curve repeats;
    `dimension` is the count of the node's own control points.
    """

    control: np.ndarray
    knots: np.ndarray
    degree: int
    weights: Optional[np.ndarray]
    closed: bool
    dimension: int

    @property
    def domain(self) -> "tuple[float, float]":
        """The parameter range the curve is defined over"""
        return float(self.knots[self.degree]), float(self.knots[len(self.control)])

    @property
    def spans(self) -> int:
        """Knot spans of non-zero length within the domain"""
        return _spans(self.knots, self.degree, len(self.control))

    def parameters(self, fractions: Any) -> np.ndarray:
        """Parameters `fractions` of the way along the domain"""
        low, high = self.domain
        return low + np.clip(np.asarray(fractions, dtype=np.float64), 0.0, 1.0) * (high - low)

    def at(self, fractions: Any) -> np.ndarray:
        """``(N, components)`` points `fractions` of the way along the curve"""
        return curve_points(self.control, self.knots, self.degree,
                            self.parameters(fractions), weights=self.weights)

    def tangent_at(self, fractions: Any) -> np.ndarray:
        """``(N, components)`` derivatives along the curve's parameter, unnormalised"""
        params = self.parameters(fractions)
        count = len(self.control)
        basis = basis_functions(params, self.knots, self.degree, count)
        derivative = basis_derivatives(params, self.knots, self.degree, count)
        if self.weights is None:
            return np.asarray(derivative @ self.control, dtype=np.float64)
        weighted = self.control * self.weights[:, None]
        denominator = basis @ self.weights
        point = (basis @ weighted) / denominator[:, None]
        # The quotient rule: the weights make the curve a ratio.
        found = ((derivative @ weighted) - point * (derivative @ self.weights)[:, None]) \
            / denominator[:, None]
        return np.asarray(found, dtype=np.float64)

    def segments(self, tessellation: int = 0, scale: float = 1.0) -> int:
        """Segments for a `tessellation` field's value (:func:`segments`)"""
        return segments(tessellation, self.dimension, self.degree, self.spans, scale)

    def sample(self, count: int) -> np.ndarray:
        """``(count + 1, components)`` points at even parameter steps, end to end

        A closed curve's last point is its first.
        """
        found = self.at(np.linspace(0.0, 1.0, max(int(count), 1) + 1))
        if self.closed:
            found[-1] = found[0]
        return found


def curve(points: Any, knot: Any, order: int, weight: Any = (),
          closed: bool = False) -> Optional[Curve]:
    """The curve a node's control points, knots, order and weights describe

    None where the order is below 2 or there are fewer points than the
    order. `points` are ``(N, components)``.
    """
    control = np.asarray(points, dtype=np.float64)
    order = int(order)
    if control.ndim != 2 or order < 2 or len(control) < order:
        return None
    count = len(control)
    weight_values = weights(weight, count)
    closed = bool(closed) and count > 2 and _coincide(control[0], control[-1], weight_values,
                                                      0, -1)
    knots = knot_vector(knot, order, count, closed)
    if weight_values is not None:
        control = control / weight_values[:, None]
    if closed:
        control = np.concatenate([control, control[1:order - 1]])
        if weight_values is not None:
            weight_values = np.concatenate([weight_values, weight_values[1:order - 1]])
    return Curve(control, knots, order - 1, weight_values, closed, count)


@dataclass
class Patch:
    """A tessellated surface

    `positions` and `normals` are one row per vertex, `fractions` the
    vertex's ``(u, v)`` as fractions of the surface's domain, and `triangles`
    three vertex indices each, counter-clockwise about the normal.
    """

    positions: np.ndarray
    normals: np.ndarray
    fractions: np.ndarray
    triangles: np.ndarray


def _empty_patch() -> Patch:
    return Patch(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
                 np.zeros((0, 2), np.float32), np.zeros((0, 3), np.uint32))


def _grid_triangles(u_points: int, v_points: int) -> np.ndarray:
    """Two triangles a cell of a lattice indexed ``u * v_points + v``"""
    rows = np.arange(u_points - 1)[:, None]
    columns = np.arange(v_points - 1)[None, :]
    corner = (rows * v_points + columns).ravel()
    first = np.stack([corner, corner + v_points, corner + v_points + 1], axis=-1)
    second = np.stack([corner, corner + v_points + 1, corner + 1], axis=-1)
    return np.concatenate([first, second]).astype(np.uint32)


def _padded(control: np.ndarray) -> np.ndarray:
    """A net of any component count as three components, for the evaluator"""
    if control.shape[-1] == 3:
        return control
    padded = np.zeros(control.shape[:-1] + (3,), dtype=np.float64)
    width = min(3, control.shape[-1])
    padded[..., :width] = control[..., :width]
    return padded


@dataclass(frozen=True)
class Net:
    """A tensor-product NURBS net of any component count, evaluated at fractions of its domain"""

    control: np.ndarray
    u_knots: np.ndarray
    v_knots: np.ndarray
    u_degree: int
    v_degree: int
    weights: Optional[np.ndarray]

    @property
    def args(self) -> "tuple[np.ndarray, np.ndarray, np.ndarray, int, int]":
        return (_padded(self.control), self.u_knots, self.v_knots, self.u_degree, self.v_degree)

    @property
    def u_domain(self) -> "tuple[float, float]":
        return (float(self.u_knots[self.u_degree]), float(self.u_knots[self.control.shape[0]]))

    @property
    def v_domain(self) -> "tuple[float, float]":
        return (float(self.v_knots[self.v_degree]), float(self.v_knots[self.control.shape[1]]))

    def parameters(self, fractions: Any) -> np.ndarray:
        """``(N, 2)`` parameters for ``(N, 2)`` fractions of the domain"""
        found = np.clip(np.asarray(fractions, dtype=np.float64).reshape(-1, 2), 0.0, 1.0)
        (u0, u1), (v0, v1) = self.u_domain, self.v_domain
        return np.stack([u0 + found[:, 0] * (u1 - u0), v0 + found[:, 1] * (v1 - v0)], axis=-1)

    def fractions(self, parameters: Any) -> np.ndarray:
        """``(N, 2)`` fractions of the domain for ``(N, 2)`` parameters"""
        found = np.asarray(parameters, dtype=np.float64).reshape(-1, 2)
        (u0, u1), (v0, v1) = self.u_domain, self.v_domain
        return np.stack([(found[:, 0] - u0) / (u1 - u0), (found[:, 1] - v0) / (v1 - v0)],
                        axis=-1)

    def at(self, fractions: Any) -> np.ndarray:
        """``(N, components)`` values at ``(N, 2)`` fractions of the domain"""
        found = surface_at(*self.args, self.parameters(fractions), weights=self.weights)
        return found[:, :self.control.shape[-1]]


@dataclass(frozen=True)
class Surface(Net):
    """A NURBS surface: a :class:`Net` of points, closed or open each way

    `u_dimension` and `v_dimension` are the node's own control point counts,
    before a closed direction's repeated rows.
    """

    u_closed: bool = False
    v_closed: bool = False
    u_dimension: int = 0
    v_dimension: int = 0

    @property
    def u_spans(self) -> int:
        return _spans(self.u_knots, self.u_degree, self.control.shape[0])

    @property
    def v_spans(self) -> int:
        return _spans(self.v_knots, self.v_degree, self.control.shape[1])

    def segments(self, u_tessellation: int = 0, v_tessellation: int = 0,
                 scale: float = 1.0) -> "tuple[int, int]":
        """Segments along u and along v for the tessellation fields' values"""
        return (segments(u_tessellation, self.u_dimension, self.u_degree, self.u_spans, scale),
                segments(v_tessellation, self.v_dimension, self.v_degree, self.v_spans, scale))

    def at(self, fractions: Any) -> Any:
        """Positions and unit normals at ``(N, 2)`` fractions of the domain"""
        params = self.parameters(fractions)
        return (surface_at(*self.args, params, weights=self.weights),
                normals_at(*self.args, params, weights=self.weights))

    def tessellate(self, u_segments: int, v_segments: int,
                   contours: Sequence[Any] = ()) -> Patch:
        """The surface as triangles, a lattice of `u_segments` by `v_segments` cells

        Contours, each ``(N, 2)`` in the surface's own knot range, keep the
        part of the domain inside an odd number of them; that part is
        triangulated about as finely as the lattice and the surface is
        evaluated at the vertices that come out.
        """
        u_segments, v_segments = max(int(u_segments), 1), max(int(v_segments), 1)
        (u0, u1), (v0, v1) = self.u_domain, self.v_domain
        rings = []
        for contour in contours:
            ring = clip_ring(np.asarray(contour, dtype=np.float64).reshape(-1, 2),
                             (u0, v0), (u1, v1))
            if len(ring) >= 3:
                rings.append(ring)
        if contours and not rings:
            return _empty_patch()
        if not rings:
            return self._lattice(u_segments, v_segments)
        cell = ((u1 - u0) / u_segments) * ((v1 - v0) / v_segments)
        domain = tessellate_domain(rings, winding=TRIM_WINDING, max_area=cell)
        if not len(domain.triangles):
            return _empty_patch()
        uv = np.asarray(domain.points, dtype=np.float64)
        return Patch(
            positions=surface_at(*self.args, uv, weights=self.weights).astype(np.float32),
            normals=normals_at(*self.args, uv, weights=self.weights).astype(np.float32),
            fractions=self.fractions(uv).astype(np.float32),
            triangles=np.asarray(domain.triangles, dtype=np.uint32))

    def _lattice(self, u_segments: int, v_segments: int) -> Patch:
        (u0, u1), (v0, v1) = self.u_domain, self.v_domain
        us = np.linspace(u0, u1, u_segments + 1)
        vs = np.linspace(v0, v1, v_segments + 1)
        positions = surface_points(*self.args, us, vs, weights=self.weights)
        normals = surface_normals(*self.args, us, vs, weights=self.weights)
        # A closed direction's seam is one row, so it is welded shut exactly.
        if self.u_closed:
            positions[-1], normals[-1] = positions[0], normals[0]
        if self.v_closed:
            positions[:, -1], normals[:, -1] = positions[:, 0], normals[:, 0]
        fractions = np.stack(np.meshgrid(np.linspace(0.0, 1.0, u_segments + 1),
                                         np.linspace(0.0, 1.0, v_segments + 1),
                                         indexing='ij'), axis=-1)
        return Patch(positions=positions.reshape(-1, 3).astype(np.float32),
                     normals=normals.reshape(-1, 3).astype(np.float32),
                     fractions=fractions.reshape(-1, 2).astype(np.float32),
                     triangles=_grid_triangles(u_segments + 1, v_segments + 1))

    def coordinate_net(self, points: Any) -> Optional[Net]:
        """A `TextureCoordinate`'s points as a net over this surface's knots

        One point per control point, u-major, evaluated through the same basis
        as the surface (not rational); None for too few points.
        """
        found = np.asarray(points, dtype=np.float64)
        count = self.u_dimension * self.v_dimension
        if found.ndim != 2 or len(found) < count:
            return None
        control = found[:count].reshape(self.v_dimension, self.u_dimension, -1).transpose(1, 0, 2)
        control = _close(control, self.u_closed, self.v_closed, self.u_degree + 1,
                         self.v_degree + 1)
        return Net(control, self.u_knots, self.v_knots, self.u_degree, self.v_degree, None)


def _net(points: Any, u_dimension: int, v_dimension: int, width: int) -> Optional[np.ndarray]:
    """The first ``u * v`` points as ``(u, v, width)``; None where there are fewer"""
    found = np.asarray(points, dtype=np.float64)
    count = u_dimension * v_dimension
    if not count or found.size < count * width:
        return None
    return found.ravel()[:count * width].reshape(v_dimension, u_dimension, width).transpose(1, 0, 2)


def _close(control: np.ndarray, u_closed: bool, v_closed: bool, u_order: int,
           v_order: int) -> np.ndarray:
    """A net with the rows a closed direction repeats"""
    if u_closed:
        control = np.concatenate([control, control[1:u_order - 1]], axis=0)
    if v_closed:
        control = np.concatenate([control, control[:, 1:v_order - 1]], axis=1)
    return control


def _orders_fit(u_dimension: int, v_dimension: int, u_order: int, v_order: int) -> bool:
    return 2 <= u_order <= u_dimension and 2 <= v_order <= v_dimension


def surface(points: Any, u_dimension: int, v_dimension: int, u_knot: Any, v_knot: Any,
            u_order: int, v_order: int, weight: Any = (), u_closed: bool = False,
            v_closed: bool = False) -> Optional[Surface]:
    """The surface a node's fields describe; None where they describe none

    `points` are u-major, ``u_dimension * v_dimension`` of them at least.
    None for an order below 2, a dimension below its order, or too few points.
    """
    u_dimension, v_dimension = int(u_dimension), int(v_dimension)
    u_order, v_order = int(u_order), int(v_order)
    if not _orders_fit(u_dimension, v_dimension, u_order, v_order):
        return None
    control = _net(points, u_dimension, v_dimension, 3)
    if control is None:
        return None
    weight_values = weights(weight, u_dimension * v_dimension)
    net_weights = (None if weight_values is None
                   else weight_values.reshape(v_dimension, u_dimension).T)
    u_closed = bool(u_closed) and all(
        _coincide(control[0, v], control[-1, v], net_weights, (0, v), (-1, v))
        for v in range(v_dimension))
    v_closed = bool(v_closed) and all(
        _coincide(control[u, 0], control[u, -1], net_weights, (u, 0), (u, -1))
        for u in range(u_dimension))
    if net_weights is not None:
        control = control / net_weights[..., None]
    control = _close(control, u_closed, v_closed, u_order, v_order)
    if net_weights is not None:
        net_weights = _close(net_weights[..., None], u_closed, v_closed, u_order, v_order)[..., 0]
    return Surface(control, knot_vector(u_knot, u_order, u_dimension, u_closed),
                   knot_vector(v_knot, v_order, v_dimension, v_closed),
                   u_order - 1, v_order - 1, net_weights, u_closed, v_closed,
                   u_dimension, v_dimension)


def texture_net(points: Any, u_dimension: int, v_dimension: int, u_knot: Any, v_knot: Any,
                u_order: int, v_order: int, weight: Any = ()) -> Optional[Net]:
    """A `NurbsTextureCoordinate`'s net of 2D points; None where it describes none"""
    u_dimension, v_dimension = int(u_dimension), int(v_dimension)
    u_order, v_order = int(u_order), int(v_order)
    if not _orders_fit(u_dimension, v_dimension, u_order, v_order):
        return None
    control = _net(points, u_dimension, v_dimension, 2)
    if control is None:
        return None
    weight_values = weights(weight, u_dimension * v_dimension)
    net_weights = (None if weight_values is None
                   else weight_values.reshape(v_dimension, u_dimension).T)
    if net_weights is not None:
        control = control / net_weights[..., None]
    return Net(control, knot_vector(u_knot, u_order, u_dimension),
               knot_vector(v_knot, v_order, v_dimension), u_order - 1, v_order - 1,
               net_weights)


def clip_ring(ring: np.ndarray, low: Sequence[float], high: Sequence[float]) -> np.ndarray:
    """A closed ring of 2D points clipped to the rectangle `low`..`high`

    A point inside the rectangle is inside the clipped ring exactly when it
    was inside the ring, so clipping every contour first keeps what the
    even-odd rule keeps within the domain. A ring already inside is returned
    as it is.
    """
    low_arr = np.asarray(low, dtype=np.float64)
    high_arr = np.asarray(high, dtype=np.float64)
    if not len(ring) or ((ring >= low_arr).all() and (ring <= high_arr).all()):
        return ring
    found = [tuple(point) for point in ring]
    for axis in (0, 1):
        for bound, keep_below in ((low_arr[axis], False), (high_arr[axis], True)):
            found = _clip_edge(found, axis, float(bound), keep_below)
            if not found:
                return np.zeros((0, 2), dtype=np.float64)
    return np.asarray(found, dtype=np.float64)


def _clip_edge(points: "list[tuple[float, ...]]", axis: int, bound: float,
               keep_below: bool) -> "list[tuple[float, ...]]":
    """One Sutherland-Hodgman pass against an axis-aligned line"""
    def inside(point: "tuple[float, ...]") -> bool:
        return point[axis] <= bound if keep_below else point[axis] >= bound

    found: "list[tuple[float, ...]]" = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        if inside(current) != inside(previous):
            share = (bound - previous[axis]) / (current[axis] - previous[axis])
            crossing = [previous[k] + share * (current[k] - previous[k]) for k in (0, 1)]
            crossing[axis] = bound
            found.append((crossing[0], crossing[1]))
        if inside(current):
            found.append(current)
    return found


def _across(curve: Curve, count: Optional[int]) -> np.ndarray:
    """A cross-section's points: at least three, as an Extrusion needs"""
    return curve.sample(max(curve.segments() if count is None else count, 2))[:, :2]


def _primitive(cross_section: np.ndarray, spine: np.ndarray, ccw: bool) -> Any:
    """An open Extrusion, smooth throughout, as one primitive"""
    built = vrml97_extrusion(cross_section=cross_section, spine=spine, begin_cap=False,
                             end_cap=False, ccw=ccw, crease_angle=math.pi,
                             texture='normalized')
    return built.merged().primitives[0]


def swept(section: Curve, trajectory: Curve, ccw: bool = True,
          section_segments: Optional[int] = None,
          trajectory_segments: Optional[int] = None) -> Any:
    """A `NurbsSweptSurface`'s mesh: the 2D `section` swept along the 3D `trajectory`

    The cross-section is placed at each trajectory point as an `Extrusion`
    places its cross-section along its spine (its points are (x, z) in the
    plane across the trajectory). Returns one glTF-shaped primitive.
    """
    across = _across(section, section_segments)
    along = trajectory.sample(trajectory.segments() if trajectory_segments is None
                              else trajectory_segments)
    return _primitive(across, _three(along), ccw)


def swung(profile: Curve, trajectory: Curve, ccw: bool = True,
          profile_segments: Optional[int] = None,
          trajectory_segments: Optional[int] = None) -> Any:
    """A `NurbsSwungSurface`'s mesh: the 2D `profile` swept along a 2D `trajectory` in the xz-plane

    The trajectory's (x, z) are the spine's; the profile is the cross-section.
    Returns one glTF-shaped primitive.
    """
    across = _across(profile, profile_segments)
    path = trajectory.sample(trajectory.segments() if trajectory_segments is None
                             else trajectory_segments)[:, :2]
    spine = np.zeros((len(path), 3), dtype=np.float64)
    spine[:, 0], spine[:, 2] = path[:, 0], path[:, 1]
    return _primitive(across, spine, ccw)


def _three(points: np.ndarray) -> np.ndarray:
    found = np.zeros((len(points), 3), dtype=np.float64)
    width = min(3, points.shape[1])
    found[:, :width] = points[:, :width]
    return found
