"""Gaussian splats' arithmetic: covariance, colour, footprint and draw order -- no GL

A splat is a 3D Gaussian: a centre, a covariance made from three scales and a
rotation, an opacity, and a colour that varies with the direction it is seen
from as spherical harmonics up to degree 3. The formulas are the ones
KHR_gaussian_splatting gives, which X3D 4.1's ``GaussianSplats`` shares; the
projection to the screen is the one in Kerbl et al., "3D Gaussian Splatting
for Real-Time Radiance Field Rendering" (2023), section 4.

:class:`SplatSet` packs a node's fields into the rows the draw uploads;
:func:`projected` and :func:`footprint` are what ``gaussian_splat.vert`` does
for each splat, written here so a test can hold the shader to them;
:class:`DepthOrder` keeps a back-to-front order and sorts again only when the
view turns or the splats change.

Quaternions are (x, y, z, w). Matrices passed in are the engine's row-vector
ones (``p_eye = p @ modelview``) except where a parameter says it is the
column-vector ``linear`` part.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

__all__ = [
    'DILATION', 'DepthOrder', 'SH_C0', 'SH_C1', 'SH_COEFFICIENTS', 'SplatSet',
    'back_to_front', 'colours', 'complete_degree', 'covariances', 'depths',
    'footprint', 'projected', 'rotations', 'sh_basis',
]

#: How many coefficients each degree of spherical harmonics adds: 1, 3, 5, 7.
SH_COEFFICIENTS = (1, 3, 5, 7)

#: The degree 0 and 1 basis constants KHR_gaussian_splatting gives.
SH_C0 = 0.2820947917738781
SH_C1 = 0.4886025119029199
_C2 = (1.092548430592079, 0.31539156525252005, 0.5462742152960395)
_C3 = (0.5900435899266435, 2.890611442640554, 0.4570457994644657,
       0.3731763325901154, 1.445305721320277)

#: Pixels squared added to each axis of a projected splat. A splat smaller
#: than a pixel is drawn a pixel wide, so it does not vanish between samples.
DILATION = 0.3

#: How far beyond the frustum's edge, as a multiple of its half-width, a
#: splat's centre is taken to be when its footprint is worked out. The
#: perspective Jacobian grows without bound off axis; a splat whose centre is
#: outside the view but whose edge reaches into it is shaped as if it were at
#: this bound.
FRUSTUM_MARGIN = 1.3

#: The deviations a splat's footprint reaches: the kernel is cut off at a
#: Mahalanobis distance of 3.
EXTENT = 3.0

#: The largest magnitude a half-precision coefficient holds.
_HALF_MAX = 65504.0


def rotations(orientations: Any) -> np.ndarray:
    """(N, 3, 3) column-vector rotation matrices of (N, 4) quaternions (x, y, z, w)

    A quaternion of any length is taken as its direction; a zero one is no turn.
    """
    q = np.asarray(orientations, np.float64).reshape(-1, 4)
    length = np.linalg.norm(q, axis=1)
    unit = np.where(length[:, None] > 0.0, q / np.where(length > 0.0, length, 1.0)[:, None],
                    (0.0, 0.0, 0.0, 1.0))
    x, y, z, w = unit.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], 1)


def covariances(scales: Any, orientations: Any) -> np.ndarray:
    """(N, 3, 3) covariances R S S R^T of (N, 3) scales and (N, 4) quaternions"""
    turn = rotations(orientations)
    spread = np.abs(np.asarray(scales, np.float64).reshape(-1, 3))
    axes = turn * spread[:, None, :]
    return np.asarray(axes @ np.swapaxes(axes, 1, 2))


def sh_basis(directions: np.ndarray, degree: int) -> np.ndarray:
    """(N, (degree + 1)^2) real spherical-harmonic basis at unit `directions`

    Ordered as X3D's fields and KHR_gaussian_splatting's attributes are: by
    degree, then from m = -l to m = l.
    """
    x, y, z = np.asarray(directions, np.float64).reshape(-1, 3).T
    terms = [np.full_like(x, SH_C0)]
    if degree >= 1:
        terms += [-SH_C1 * y, SH_C1 * z, -SH_C1 * x]
    if degree >= 2:
        xx, yy, zz = x * x, y * y, z * z
        terms += [_C2[0] * x * y, -_C2[0] * y * z, _C2[1] * (2 * zz - xx - yy),
                  -_C2[0] * x * z, _C2[2] * (xx - yy)]
    if degree >= 3:
        terms += [-_C3[0] * y * (3 * xx - yy), _C3[1] * x * y * z,
                  -_C3[2] * y * (4 * zz - xx - yy), _C3[3] * z * (2 * zz - 3 * xx - 3 * yy),
                  -_C3[2] * x * (4 * zz - xx - yy), _C3[4] * z * (xx - yy),
                  -_C3[0] * x * (xx - 3 * yy)]
    return np.stack(terms, -1)


def _degree_of(terms: int) -> int:
    """The degree whose basis has `terms` terms, for 1, 4, 9 or 16"""
    degree = int(round(math.sqrt(terms))) - 1
    if (degree + 1) ** 2 != terms or not 0 <= degree <= 3:
        raise ValueError('%d spherical-harmonic coefficients is not a whole degree '
                         'from 0 to 3' % terms)
    return degree


def colours(coefficients: Any, directions: Any) -> np.ndarray:
    """(N, 3) colours of (N, K, 3) coefficients seen along (N, 3) `directions`

    The basis sum plus 0.5, held to [0, 1]. A direction need not be unit
    length; a zero one reads degree 0 alone.
    """
    coefficients = np.asarray(coefficients, np.float64)
    directions = np.asarray(directions, np.float64).reshape(-1, 3)
    length = np.linalg.norm(directions, axis=1)
    unit = directions / np.where(length > 0.0, length, 1.0)[:, None]
    basis = sh_basis(unit, _degree_of(coefficients.shape[1]))
    summed = np.einsum('nk,nkc->nc', basis, coefficients) + 0.5
    return np.asarray(np.clip(summed, 0.0, 1.0))


def complete_degree(counts: Sequence[int], count: int) -> int:
    """The highest degree whose coefficients and every lower degree's have `count` rows

    `counts` are the row counts of the coefficient fields in order (degree 0
    first). A degree is complete when each of its fields holds a row per
    splat; -1 where degree 0 is not.
    """
    degree, start = -1, 0
    for wanted in SH_COEFFICIENTS:
        held = list(counts[start:start + wanted])
        if len(held) < wanted or not count or any(int(rows) < count for rows in held):
            break
        degree += 1
        start += wanted
    return degree


def projected(covariance: Any, centres: Any, linear: Any, focal: Sequence[float],
              *, perspective: bool = True, dilation: float = DILATION,
              limit: Optional[Sequence[float]] = None) -> np.ndarray:
    """(N, 3) screen covariances (a, b, c) in pixels squared, [[a, b], [b, c]]

    `covariance` is (3, 3) or (N, 3, 3) in the splat's own frame, `linear` the
    column-vector 3x3 taking it to the eye's, `centres` the (N, 3) eye-space
    centres (in front is z < 0), `focal` the projection's x and y scale in
    pixels. `limit` bounds a perspective centre's x/-z and y/-z, the tangent
    the frustum's edge is at times :data:`FRUSTUM_MARGIN`; None leaves them
    as they are. `dilation` is added to a and c.
    """
    centres = np.asarray(centres, np.float64).reshape(-1, 3)
    linear = np.asarray(linear, np.float64)
    sigma = np.broadcast_to(np.asarray(covariance, np.float64), (len(centres), 3, 3))
    eye = linear @ sigma @ linear.T
    fx, fy = (float(value) for value in focal)
    rows = np.zeros((len(centres), 2, 3))
    if perspective:
        w = -centres[:, 2]
        tangent = centres[:, :2] / w[:, None]
        if limit is not None:
            tangent = np.clip(tangent, -np.asarray(limit, np.float64), np.asarray(limit, np.float64))
        rows[:, 0, 0] = fx / w
        rows[:, 0, 2] = fx * tangent[:, 0] / w
        rows[:, 1, 1] = fy / w
        rows[:, 1, 2] = fy * tangent[:, 1] / w
    else:
        rows[:, 0, 0] = fx
        rows[:, 1, 1] = fy
    screen = rows @ eye @ np.swapaxes(rows, 1, 2)
    return np.stack([screen[:, 0, 0] + dilation, screen[:, 0, 1],
                     screen[:, 1, 1] + dilation], -1)


def footprint(spread: Any) -> tuple[np.ndarray, np.ndarray]:
    """((N, 2), (N, 2)): the half-axes in pixels of each (a, b, c) screen covariance's quad

    Each half-axis is an eigenvector scaled to :data:`EXTENT` deviations, the
    major first. A quad spanning them covers the splat's 3-sigma ellipse.
    """
    a, b, c = np.asarray(spread, np.float64).reshape(-1, 3).T
    middle = 0.5 * (a + c)
    radius = np.sqrt(np.maximum(middle * middle - (a * c - b * b), 0.0))
    major = np.maximum(middle + radius, 0.0)
    minor = np.maximum(middle - radius, 0.0)
    direction = np.stack([b, major - a], -1)
    flat = np.abs(b) <= 1e-12 * np.maximum(np.abs(a) + np.abs(c), 1e-300)
    direction[flat] = np.where((a >= c)[flat, None], (1.0, 0.0), (0.0, 1.0))
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    across = np.stack([-direction[:, 1], direction[:, 0]], -1)
    return (direction * (EXTENT * np.sqrt(major))[:, None],
            across * (EXTENT * np.sqrt(minor))[:, None])


def depths(positions: Any, modelview: Any) -> np.ndarray:
    """(N,) eye-space z of (N, 3) `positions` under a row-vector `modelview`"""
    matrix = np.asarray(modelview, np.float64)
    points = np.asarray(positions, np.float64).reshape(-1, 3)
    return np.asarray(points @ matrix[:3, 2] + matrix[3, 2])


#: Bits of depth the order is sorted on: a 16-bit key sorts by radix in
#: linear time.
ORDER_BITS = 16


def back_to_front(eye_depths: Any) -> np.ndarray:
    """uint32 indices of `eye_depths` (eye-space z), the farthest first

    The depths are quantised to :data:`ORDER_BITS` bits across their range
    and sorted stably, so the work is linear in the count. Splats closer
    together than the range over 65535 keep their index order.
    """
    z = np.asarray(eye_depths, np.float64).ravel()
    if not len(z):
        return np.zeros(0, np.uint32)
    low, high = float(z.min()), float(z.max())
    with np.errstate(over='ignore', invalid='ignore'):
        span = high - low
    if not math.isfinite(span):
        return np.argsort(z, kind='stable').astype(np.uint32)
    if span <= 0.0:
        return np.arange(len(z), dtype=np.uint32)
    steps = (1 << ORDER_BITS) - 1
    keys = np.minimum((z - low) * (steps / span), steps).astype(np.uint16)
    return np.argsort(keys, kind='stable').astype(np.uint32)


class DepthOrder:
    """A back-to-front order of one splat set, sorted again only when it would change

    The order is by eye-space depth, which is the splat's distance along the
    view direction in its own frame. Moving the camera without turning it, or
    scaling the view, leaves that order as it is, so :meth:`update` sorts only
    when the view direction in the splats' frame has turned more than
    `tolerance` radians since the last sort, or the splats themselves have
    changed (a new `generation`).
    """

    def __init__(self, tolerance: float = math.radians(0.25)) -> None:
        self.tolerance = float(tolerance)
        self._cosine = math.cos(self.tolerance)
        self.order: np.ndarray = np.zeros(0, np.uint32)
        self.direction: Optional[np.ndarray] = None
        self.generation: Any = None
        #: How many sorts this order has made.
        self.sorts = 0

    @staticmethod
    def view_direction(modelview: Any) -> np.ndarray:
        """The unit direction eye depth is measured along, in the splats' frame"""
        axis = np.asarray(modelview, np.float64)[:3, 2]
        length = float(np.linalg.norm(axis))
        return axis / length if length > 0.0 else np.array((0.0, 0.0, 1.0))

    def holds(self, direction: np.ndarray, generation: Any) -> bool:
        """Whether the order kept is good for a view along unit `direction`"""
        return (generation == self.generation and self.direction is not None
                and float(np.dot(direction, self.direction)) >= self._cosine)

    def update(self, positions: Any, modelview: Any,
               generation: Any) -> tuple[np.ndarray, bool]:
        """(order, whether it was sorted now) for `positions` under `modelview`"""
        matrix = np.asarray(modelview, np.float64)
        direction = self.view_direction(matrix)
        if self.holds(direction, generation):
            return self.order, False
        self.order = back_to_front(depths(positions, matrix))
        self.direction = direction
        self.generation = generation
        self.sorts += 1
        return self.order, True


@dataclass
class SplatSet:
    """A splat node's fields, checked and packed for the draw

    ``centres`` (N, 3), ``opacities`` (N,), ``covariances`` (N, 6) as xx, xy,
    xz, yy, yz, zz, and ``harmonics`` (N, K, 3) with K = (``degree`` + 1)^2.
    ``short`` names each field that held fewer rows than ``positions`` and
    how many; ``dropped`` counts splats left out for a value that is not
    finite.
    """

    centres: np.ndarray
    opacities: np.ndarray
    covariances: np.ndarray
    harmonics: np.ndarray
    degree: int
    short: dict[str, int] = field(default_factory=dict)
    dropped: int = 0

    @property
    def count(self) -> int:
        """How many splats the set draws"""
        return len(self.centres)

    @classmethod
    def from_fields(cls, positions: Any, orientations: Any, scales: Any,
                    opacities: Any, harmonics: Sequence[Any]) -> SplatSet:
        """The set the fields describe

        The splat count is that of ``positions``, shortened to any shorter
        field among ``scales``, ``orientations`` and ``opacities``.
        ``scales`` is required; an empty ``orientations`` is no turn, an
        empty ``opacities`` is opaque. ``harmonics`` are the coefficient
        fields in order; the degree read is the highest complete one
        (:func:`complete_degree`), and with none the colour is 0.5 grey.
        """
        points = np.asarray(positions, np.float64).reshape(-1, 3)
        spread = np.asarray(scales, np.float64).reshape(-1, 3)
        turns = np.asarray(orientations, np.float64).reshape(-1, 4)
        alpha = np.asarray(opacities, np.float64).ravel()
        coefficient_rows = [np.asarray(values, np.float64).reshape(-1, 3) for values in harmonics]
        count = len(points)
        short: dict[str, int] = {}
        for name, rows in (('scales', spread), ('orientations', turns),
                           ('opacities', alpha)):
            if (len(rows) or name == 'scales') and len(rows) < count:
                short[name] = len(rows)
        count = min([count] + list(short.values()))
        if not len(turns):
            turns = np.tile((0.0, 0.0, 0.0, 1.0), (count, 1))
        if not len(alpha):
            alpha = np.ones(count)
        degree = max(complete_degree([len(rows) for rows in coefficient_rows], count), 0)
        terms = (degree + 1) ** 2
        coefficients = np.zeros((count, terms, 3))
        for index, rows in enumerate(coefficient_rows[:terms]):
            if len(rows) >= count:
                coefficients[:, index] = rows[:count]
        points, spread, turns, alpha = points[:count], spread[:count], turns[:count], alpha[:count]
        finite = (np.isfinite(points).all(1) & np.isfinite(spread).all(1)
                  & np.isfinite(turns).all(1) & np.isfinite(alpha))
        dropped = int(count - finite.sum())
        sigma = covariances(spread[finite], turns[finite])
        packed = sigma[:, (0, 0, 0, 1, 1, 2), (0, 1, 2, 1, 2, 2)]
        return cls(centres=points[finite], opacities=np.clip(alpha[finite], 0.0, 1.0),
                   covariances=packed,
                   harmonics=np.nan_to_num(coefficients[finite], nan=0.0),
                   degree=degree, short=short, dropped=dropped)

    def geometry_rows(self) -> np.ndarray:
        """(N, 12) float32: centre, opacity, the six covariance terms, two spare"""
        rows = np.zeros((self.count, 12), np.float32)
        rows[:, :3] = self.centres
        rows[:, 3] = self.opacities
        rows[:, 4:10] = self.covariances
        return rows

    def harmonic_rows(self) -> np.ndarray:
        """(N, 4T) float32: each splat's coefficients r, g, b in turn, padded to whole texels

        Held to the range half precision represents, since the draw stores
        them as half floats.
        """
        flat = self.harmonics.reshape(self.count, -1)
        width = -(-flat.shape[1] // 4) * 4
        rows = np.zeros((self.count, width), np.float32)
        rows[:, :flat.shape[1]] = np.clip(flat, -_HALF_MAX, _HALF_MAX)
        return rows

    def bounds(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """(low, high) of every splat's 3-sigma ellipsoid; None for an empty set"""
        if not self.count:
            return None
        reach = EXTENT * np.sqrt(np.maximum(self.covariances[:, (0, 3, 5)], 0.0))
        return ((self.centres - reach).min(axis=0), (self.centres + reach).max(axis=0))
