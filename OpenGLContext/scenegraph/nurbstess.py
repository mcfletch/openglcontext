"""Tessellation service for NURBS surfaces: control net and knots to triangles.

A :class:`~OpenGLContext.scenegraph.nurbs.NurbsSurface` node is a control net,
a knot vector each way, and optionally a weight and a colour per control point.
:func:`tessellate_surface` evaluates it into positions, normals, parametric
texture coordinates, colours and triangle indices, which the surface nodes then
draw -- through a VBO under the core profile, through client arrays under the
compatibility one.

The evaluation is :mod:`opengl_extrusions.nurbs`; a trimmed surface's domain is
triangulated by the same package's constrained Delaunay tessellator and the
surface is evaluated at the vertices that come out. Nothing here calls GL, so a
surface can be tessellated with no context current -- and tested with none
either.

Parameter conventions
    The node's ``controlPoint`` is v-major: ``uDimension * vDimension`` points
    with u varying fastest, so it reshapes to ``(vDimension, uDimension, 3)``.
    The evaluator pairs its first control axis with its first knot vector, so
    this module hands it the net in that order, with ``vKnot`` first. That makes
    its first parameter the surface's *v*, and so its normal
    ``dp/dv x dp/du`` -- which is the sense the VRML97 NURBS nodes have always
    had, and what keeps a scene's surfaces facing the way they were authored.

    Trimming contours are in the same order, ``(v, u)``, being the coordinates a
    trim curve has always been written in here.

    Texture coordinates are the other way round: ``(u, v)``, each the fraction
    of its own knot range, which is what a parametric texture map on a surface
    means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import numpy as np
from opengl_extrusions import tessellate
from opengl_extrusions.nurbs import (
    NurbsError, normals_at, surface_at, surface_grid, surface_points,
)

from OpenGL.arrays import vbo
from OpenGL.GL import GL_ELEMENT_ARRAY_BUFFER

log = logging.getLogger(__name__)

__all__ = [
    'DEFAULT_STEP',
    'MAX_INTERVALS',
    'SurfaceTessellation',
    'TRIM_CURVE_STEPS',
    'build_surface_vbo',
    'intervals_for',
    'surface_intervals',
    'tessellate_surface',
]

#: Sample intervals per unit of parameter domain when nothing asks for a rate.
#: A surface whose knots run 0..1 -- which is nearly all of them -- is therefore
#: sampled 30 by 30.
DEFAULT_STEP = 30.0

#: The most intervals one direction may be given. A step rate multiplies by the
#: knot range, so an unusual range can otherwise ask for a mesh far past what
#: any sampling rate intended; this is where that stops.
MAX_INTERVALS = 512

#: Points evaluated along a NURBS trimming curve. A trim curve bounds a region
#: of the parameter square rather than the surface itself, so its own curvature
#: is the only thing this has to follow.
TRIM_CURVE_STEPS = 32

#: Which regions of a trimmed domain come out solid. A trimming loop keeps what
#: lies to its left, so a counter-clockwise loop is a boundary, a clockwise one
#: inside it is a hole, and a clockwise loop on its own encloses nothing at all:
#: the positive winding rule.
TRIM_WINDING = 'positive'


@dataclass
class SurfaceTessellation:
    """A tessellated NURBS surface, as arrays a renderer can upload.

    ``positions``, ``normals`` and ``texcoords`` hold one row per vertex, and
    ``colors`` either one RGBA row per vertex or ``None`` where the surface
    carries no colour. ``indices`` is one row of three vertex indices per
    triangle.
    """

    positions: np.ndarray
    normals: np.ndarray
    texcoords: np.ndarray
    colors: Optional[np.ndarray]
    indices: np.ndarray

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def triangle_count(self) -> int:
        return len(self.indices)

    @property
    def index_count(self) -> int:
        """How many indices a draw call consumes."""
        return int(self.indices.size)


def _empty() -> SurfaceTessellation:
    return SurfaceTessellation(
        positions=np.zeros((0, 3), np.float32),
        normals=np.zeros((0, 3), np.float32),
        texcoords=np.zeros((0, 2), np.float32),
        colors=None,
        indices=np.zeros((0, 3), np.uint32),
    )


def intervals_for(step: float, span: float) -> int:
    """How many sample intervals a rate of ``step`` per unit buys over ``span``.

    The rate is per unit of parameter domain, so a surface whose knots run twice
    as far is sampled twice as often at the same rate and its triangles come out
    the same size.
    """
    if not np.isfinite(step) or not np.isfinite(span) or step <= 0 or span <= 0:
        return 1
    return int(min(MAX_INTERVALS, max(1, round(step * span))))


def _degree(knot: Any, dimension: int, name: str) -> int:
    """The degree a knot vector of this length implies over this many points."""
    degree = len(knot) - dimension - 1
    if degree < 1:
        raise NurbsError(
            'a %s knot vector of %d over %d control points implies degree %d'
            % (name, len(knot), dimension, degree)
        )
    return degree


class _Surface:
    """A NURBS surface node's fields, read once and checked.

    The node is a scenegraph object whose fields are read through the VRML97
    machinery; this is the plain data underneath, in the evaluator's own order
    (see the module docstring), so the tessellation paths below share one
    reading of it.
    """

    def __init__(self, surface: Any) -> None:
        u_dimension = int(surface.uDimension)
        v_dimension = int(surface.vDimension)
        control = np.asarray(surface.controlPoint, dtype=np.float64)
        if control.size != u_dimension * v_dimension * 3:
            raise NurbsError(
                'a %d by %d control net needs %d coordinates, got %d'
                % (u_dimension, v_dimension, u_dimension * v_dimension * 3,
                   control.size)
            )
        # v-major, and so the evaluator's first axis: see the module docstring.
        self.control = control.reshape(v_dimension, u_dimension, 3)
        self.v_knot = np.asarray(surface.vKnot, dtype=np.float64).ravel()
        self.u_knot = np.asarray(surface.uKnot, dtype=np.float64).ravel()
        self.v_degree = _degree(self.v_knot, v_dimension, 'v')
        self.u_degree = _degree(self.u_knot, u_dimension, 'u')
        self.v_span = self._span(self.v_knot, self.v_degree, v_dimension)
        self.u_span = self._span(self.u_knot, self.u_degree, u_dimension)

        weight = np.asarray(getattr(surface, 'weight', ()), dtype=np.float64).ravel()
        if weight.size == u_dimension * v_dimension:
            self.weights: Optional[np.ndarray] = weight.reshape(
                v_dimension, u_dimension)
        else:
            if weight.size:
                log.warning(
                    '%s carries %d weights for %d control points -> ignoring them',
                    surface, weight.size, u_dimension * v_dimension,
                )
            self.weights = None

        color = np.asarray(getattr(surface, 'color', ()), dtype=np.float64)
        if color.size == u_dimension * v_dimension * 3:
            self.colors: Optional[np.ndarray] = color.reshape(
                v_dimension, u_dimension, 3)
        else:
            if color.size:
                log.warning(
                    '%s carries %d colour components for %d control points'
                    ' -> ignoring them',
                    surface, color.size, u_dimension * v_dimension,
                )
            self.colors = None

    @staticmethod
    def _span(knot: np.ndarray, degree: int, dimension: int) -> tuple[float, float]:
        """The parameter range a knot vector is defined over."""
        return float(knot[degree]), float(knot[dimension])

    @property
    def args(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
        """The five positional arguments every evaluator entry point takes."""
        return (self.control, self.v_knot, self.u_knot, self.v_degree, self.u_degree)

    def texcoords(self, first: np.ndarray, second: np.ndarray) -> np.ndarray:
        """``(u, v)`` fractions of the knot ranges, for parameters in node order.

        ``first`` runs along v and ``second`` along u, so the two swap on the way
        out: a texture coordinate is ``(u, v)``.
        """
        v0, v1 = self.v_span
        u0, u1 = self.u_span
        v = (first - v0) / (v1 - v0) if v1 > v0 else np.zeros_like(first)
        u = (second - u0) / (u1 - u0) if u1 > u0 else np.zeros_like(second)
        return np.stack([u, v], axis=-1)


def surface_intervals(
    surface: Any,
    sampling: Any = None,
    u_step: Optional[float] = None,
    v_step: Optional[float] = None,
) -> tuple[int, int]:
    """How many intervals to sample a surface along v and along u.

    ``u_step``/``v_step`` are explicit rates -- what the distance-LOD paths pass
    to tessellate a far-off surface coarsely -- and override ``sampling``. A
    sampling node supplies its own rate; with neither, :data:`DEFAULT_STEP`.

    Returned in the evaluator's order, v first.
    """
    parsed = _Surface(surface)
    if u_step is not None or v_step is not None:
        u_rate = float(u_step if u_step is not None else DEFAULT_STEP)
        v_rate = float(v_step if v_step is not None else DEFAULT_STEP)
    elif sampling is not None and hasattr(sampling, 'steps'):
        u_rate, v_rate = sampling.steps()
    else:
        u_rate = v_rate = DEFAULT_STEP
    v0, v1 = parsed.v_span
    u0, u1 = parsed.u_span
    return intervals_for(v_rate, v1 - v0), intervals_for(u_rate, u1 - u0)


def _grid_tessellation(
    parsed: _Surface, v_intervals: int, u_intervals: int
) -> SurfaceTessellation:
    """An untrimmed surface: a regular lattice over the whole domain."""
    mesh = surface_grid(
        *parsed.args,
        v_intervals + 1,
        u_intervals + 1,
        weights=parsed.weights,
    )
    colors = None
    if parsed.colors is not None:
        v0, v1 = parsed.v_span
        u0, u1 = parsed.u_span
        # The colour net is evaluated through the same basis as the surface, so
        # a colour follows its control point across the tessellation however
        # finely it is sampled. It is not rational: the weights shape the
        # geometry, not what is painted on it.
        rgb = surface_points(
            parsed.colors, parsed.v_knot, parsed.u_knot,
            parsed.v_degree, parsed.u_degree,
            np.linspace(v0, v1, v_intervals + 1),
            np.linspace(u0, u1, u_intervals + 1),
        )
        colors = _opaque(rgb.reshape(-1, 3))
    return SurfaceTessellation(
        positions=mesh.positions,
        normals=mesh.normals,
        # surface_grid's texcoords run (first, second) = (v, u).
        texcoords=np.ascontiguousarray(mesh.texcoords[:, ::-1]),
        colors=colors,
        indices=mesh.indices,
    )


def _trimmed_tessellation(
    parsed: _Surface, contours: Sequence[Any], v_intervals: int, u_intervals: int
) -> SurfaceTessellation:
    """A trimmed surface: triangulate the kept domain, evaluate its vertices."""
    rings = []
    for contour in contours:
        ring = np.asarray(contour.contour(), dtype=np.float64)
        if len(ring) >= 3:
            rings.append(ring)
    if not rings:
        return _grid_tessellation(parsed, v_intervals, u_intervals)

    v0, v1 = parsed.v_span
    u0, u1 = parsed.u_span
    # Refine to about the triangle size the sampling rate asks for, so a trimmed
    # surface is sampled as finely as an untrimmed one at the same rate rather
    # than only where its outline happens to have vertices. Refinement splits a
    # boundary edge that its own new points encroach on, so the outline follows
    # the surface as closely as the middle does without being subdivided first.
    cell = ((v1 - v0) / v_intervals) * ((u1 - u0) / u_intervals)
    domain = tessellate(rings, winding=TRIM_WINDING, max_area=cell)
    if not len(domain.triangles):
        log.warning('trimming contours left no surface to render')
        return _empty()

    uv = domain.points
    positions = surface_at(*parsed.args, uv, weights=parsed.weights)
    normals = normals_at(*parsed.args, uv, weights=parsed.weights)
    colors = None
    if parsed.colors is not None:
        rgb = surface_at(
            parsed.colors, parsed.v_knot, parsed.u_knot,
            parsed.v_degree, parsed.u_degree, uv,
        )
        colors = _opaque(rgb)
    return SurfaceTessellation(
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        texcoords=parsed.texcoords(uv[:, 0], uv[:, 1]).astype(np.float32),
        colors=colors,
        indices=domain.triangles.astype(np.uint32),
    )


def _opaque(rgb: np.ndarray) -> np.ndarray:
    """RGB rows as opaque RGBA."""
    rgba = np.ones((len(rgb), 4), np.float32)
    rgba[:, :3] = rgb
    return rgba


def tessellate_surface(
    surface: Any,
    trimming_contours: Any = None,
    sampling: Any = None,
    u_step: Optional[float] = None,
    v_step: Optional[float] = None,
) -> SurfaceTessellation:
    """Evaluate a NURBS surface node into triangles.

    :param surface: a node with ``controlPoint``, ``uKnot``, ``vKnot``,
        ``uDimension`` and ``vDimension``, and optionally ``weight`` and
        ``color``.
    :param trimming_contours: :class:`~OpenGLContext.scenegraph.nurbstrim.Contour2D`
        nodes bounding the part of the domain to keep.
    :param sampling: a sampling node naming how finely to sample.
    :param u_step: sample intervals per unit of the u knot range, overriding
        ``sampling``.
    :param v_step: the same along v.

    :raises opengl_extrusions.nurbs.NurbsError: for a control net, knot vector
        or weight array that does not describe a surface.
    """
    parsed = _Surface(surface)
    v_intervals, u_intervals = surface_intervals(
        surface, sampling=sampling, u_step=u_step, v_step=v_step)
    if trimming_contours:
        return _trimmed_tessellation(
            parsed, trimming_contours, v_intervals, u_intervals)
    return _grid_tessellation(parsed, v_intervals, u_intervals)


# Interleaved vertex layouts the surface nodes' shader path reads. Both put the
# normal before the position, and the colour, where there is one, before both.
NORMAL_POSITION_STRIDE = 24
COLOR_NORMAL_POSITION_STRIDE = 40


def interleave(tessellation: SurfaceTessellation) -> np.ndarray:
    """One float32 row per vertex: colour (where present), normal, position."""
    if tessellation.colors is None:
        return np.hstack([tessellation.normals, tessellation.positions]).astype(
            np.float32, copy=False)
    return np.hstack([
        tessellation.colors, tessellation.normals, tessellation.positions,
    ]).astype(np.float32, copy=False)


def build_surface_vbo(
    tessellation: SurfaceTessellation,
) -> tuple[Any, Any, int, bool]:
    """Upload a tessellation as an interleaved vertex buffer and an index buffer.

    Returns ``(vertices, indices, index_count, has_colors)``, or
    ``(None, None, 0, False)`` where there is nothing to draw. Indexed, because
    a lattice shares each interior vertex between six triangles: drawing it as
    a soup would upload six copies of it.
    """
    if not tessellation.triangle_count:
        return None, None, 0, False
    vertices = vbo.VBO(interleave(tessellation))
    indices = vbo.VBO(
        tessellation.indices.astype(np.uint32, copy=False).ravel(),
        target=GL_ELEMENT_ARRAY_BUFFER,
    )
    return vertices, indices, tessellation.index_count, tessellation.colors is not None
