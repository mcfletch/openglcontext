"""Tessellate the Utah Teapot Bezier patches into renderable vertex arrays.

The Newell teapot is described as 32 bicubic Bezier patches (see
:mod:`OpenGLContext.scenegraph.teapot_nurbs_data`).  This module builds a
:class:`~OpenGLContext.scenegraph.nurbs.NurbsSurface` for each patch and runs
it through the GLU NURBS tessellators in
:mod:`OpenGLContext.scenegraph.nurbs` to produce interleaved ``N3F_V3F``
triangle arrays.

GLU NURBS tessellation drives the GL state machine, so a context must be
current when these functions are called; tessellation therefore happens
lazily at first render rather than at import time.

The Utah Teapot was modelled by Martin Newell in 1975 at the University of
Utah.  See https://graphics.cs.utah.edu/teapot/ for its history.
"""
import logging
from typing import Any, Optional

import numpy as np

from OpenGLContext.scenegraph import nurbs
from OpenGLContext.scenegraph.teapot_nurbs_data import (
    CONTROL_POINTS,
    PATCH_GROUPS,
    PART_ORDER,
    LID_PART,
)

log = logging.getLogger(__name__)

# A bicubic Bezier patch is a NURBS surface of order 4 with a clamped knot
# vector [0,0,0,0,1,1,1,1] in both parametric directions.
_BEZIER_KNOT = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


def _grid_cell(rect: Any, cols: int, rows: int, col: int,
               row: int) -> tuple[float, float, float, float]:
    """Affine ``(su, sv, ou, ov)`` mapping [0,1]^2 into cell (col,row) of ``rect``.

    ``rect`` is ``(u0, v0, u1, v1)``; the region is a ``cols x rows`` grid and
    the returned affine sends a patch's parametric (u, v) into that sub-cell.
    """
    u0, v0, u1, v1 = rect
    cw = (u1 - u0) / cols
    ch = (v1 - v0) / rows
    return (cw, ch, u0 + col * cw, v0 + row * ch)


def injective_uv_transforms() -> tuple[
        list[tuple[float, float, float, float]], list[tuple[float, float, float, float]],
        list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]:
    """Per-patch exterior/interior atlas affines for the injective layout.

    Implements the Utah Teapot "injective, with interior" texture layout
    (https://graphics.cs.utah.edu/teapot/) adapted to this single-shell teapot:
    every patch is textured once for its exterior face and once for its interior
    (back) face, into non-overlapping regions of the unit square, so the whole
    teapot maps injectively.

      * bottom half (v<=0.5): body + bottom cap, as a 4-around x 4-band grid
        (body's 3 bands plus the bottom disk as a 4th band); exterior fills
        v in [0.25, 0.5], interior mirrors it in v in [0, 0.25].
      * top half (v>=0.5): four u-columns for handle / lid-knob / lid / spout;
        each column's exterior is the lower square (v in [0.5, 0.75]) and its
        interior the upper square (v in [0.75, 1.0]), packed 2x2.

    Returns ``(base_ext, base_int, lid_ext, lid_int)``: lists of affines parallel
    to the base patch order (PART_ORDER concatenation) and the lid patches.
    """
    body_ext = (0.0, 0.25, 1.0, 0.5)
    body_int = (0.0, 0.0, 1.0, 0.25)
    # Top-half columns, each split exterior (lower) / interior (upper).
    cols = {
        'handle': 0.0, 'knob': 0.25, 'lid': 0.5, 'spout': 0.75,
    }

    def top(part: str, interior: bool) -> tuple[float, float, float, float]:
        u0 = cols[part]
        v0 = 0.75 if interior else 0.5
        return (u0, v0, u0 + 0.25, v0 + 0.25)

    base_ext: list[tuple[float, float, float, float]] = []
    base_int: list[tuple[float, float, float, float]] = []
    # body: 12 patches, band-major (band = i//4, around = i%4) -> rows 0..2.
    for i in range(len(PATCH_GROUPS['body'])):
        band, around = i // 4, i % 4
        base_ext.append(_grid_cell(body_ext, 4, 4, around, band))
        base_int.append(_grid_cell(body_int, 4, 4, around, band))
    # handle: 4 patches -> 2x2 in its top-half column.
    for i in range(len(PATCH_GROUPS['handle'])):
        base_ext.append(_grid_cell(top('handle', False), 2, 2, i % 2, i // 2))
        base_int.append(_grid_cell(top('handle', True), 2, 2, i % 2, i // 2))
    # spout: 4 patches -> 2x2.
    for i in range(len(PATCH_GROUPS['spout'])):
        base_ext.append(_grid_cell(top('spout', False), 2, 2, i % 2, i // 2))
        base_int.append(_grid_cell(top('spout', True), 2, 2, i % 2, i // 2))
    # bottom cap: 4 patches -> the 4th band (row 3) of the body grid.
    for i in range(len(PATCH_GROUPS['bottom'])):
        base_ext.append(_grid_cell(body_ext, 4, 4, i, 3))
        base_int.append(_grid_cell(body_int, 4, 4, i, 3))

    # lid: 8 patches = knob (0..3) then lid skirt (4..7). Knob shares the 'knob'
    # column; the skirt uses the 'lid' column.
    lid_ext: list[tuple[float, float, float, float]] = []
    lid_int: list[tuple[float, float, float, float]] = []
    for i in range(len(PATCH_GROUPS['lid'])):
        part = 'knob' if i < 4 else 'lid'
        j = i % 4
        lid_ext.append(_grid_cell(top(part, False), 2, 2, j % 2, j // 2))
        lid_int.append(_grid_cell(top(part, True), 2, 2, j % 2, j // 2))
    return base_ext, base_int, lid_ext, lid_int

# Floats per interleaved T2F_N3F_V3F vertex (texcoord, normal, then position).
# The texcoord is the patch's parametric (u, v) in [0, 1], captured from GLU;
# it matches the vertex shaders' interleaved layout (loc 0 texcoord, 1 normal,
# 2 position) so a texture/PBR material can be mapped onto the teapot.
FLOATS_PER_VERTEX = 8


def _orient(point: Any) -> tuple[float, float, float]:
    """Map a raw Newell control point to glutSolidTeapot(1.0) space.

    The Newell dataset is z-up with the body resting on z=0.  GLUT renders it
    by translating z by -1.5, scaling by 0.5, and rotating 270 degrees about
    x to make it y-up.  Baking the same transform here keeps the NURBS teapot
    aligned with the GLUT one for comparison; ``size`` is applied separately
    at render time, matching glutSolidTeapot's scale argument.  The transform
    is a proper rotation (determinant +1), so tessellated normals stay
    outward-facing.
    """
    x, y, z = point
    return (0.5 * x, 0.5 * (z - 1.5), -0.5 * y)


def _patch_surface(indices: Any, sampling: Any) -> Any:
    """Build a NurbsSurface for a single 16-point Bezier patch.

    The 4x4 control grid is transposed (u and v swapped).  The Newell patch
    ordering is left-handed relative to GLU's convention, so without this the
    tessellator emits inward-facing normals and clockwise winding; swapping
    the parametric directions flips the surface derivatives' cross product and
    yields outward normals with counter-clockwise winding.
    """
    points = [_orient(CONTROL_POINTS[i]) for i in indices]
    points = [points[u * 4 + v] for v in range(4) for u in range(4)]
    return nurbs.NurbsSurface(
        uDimension=4,
        vDimension=4,
        uOrder=4,
        vOrder=4,
        uKnot=_BEZIER_KNOT,
        vKnot=_BEZIER_KNOT,
        controlPoint=points,
        sampling=sampling,
    )


def _emit_face(out: list[float], texcoords: Any, normals: Any, vertices: Any,
               idx: int, xform: Any, flip: bool) -> None:
    """Append one T2F_N3F_V3F vertex, atlas-remapped and optionally inverted."""
    su, sv, ou, ov = xform
    u, v = texcoords[idx] if idx < len(texcoords) else (0.0, 0.0)
    out.append(ou + su * u)
    out.append(ov + sv * v)
    n = normals[idx] if idx < len(normals) else (0.0, 0.0, 1.0)
    if flip:
        out.extend((-n[0], -n[1], -n[2]))
    else:
        out.extend(n)
    out.extend(vertices[idx])


def _emit_patch(callback: Any, out: list[float], ext_xform: Any,
                int_xform: Any = None) -> None:
    """Append a tessellated patch's triangles to ``out`` as T2F_N3F_V3F floats.

    ``ext_xform`` is an ``(su, sv, ou, ov)`` affine mapping the patch's raw
    parametric (u, v) in [0, 1] into its exterior slot in the injective atlas
    (``atlas_u = ou + su*u``).  When ``int_xform`` is given a second, interior
    copy of every triangle is emitted with reversed winding and negated normals,
    mapped into the interior atlas slot; that copy is the back side of the shell,
    kept as its own faces so each face carries a single UV (no per-face facing
    test needed) and shows the interior when viewed through the teapot's mouth.
    Interior faces are back-facing from outside, so backface culling hides them
    there without z-fighting against the coincident exterior faces.
    """
    vertices = callback.vertices
    normals = callback.normals
    texcoords = callback.texcoords
    triangles = callback.build_triangles()
    for tri in triangles:
        for idx in tri:
            _emit_face(out, texcoords, normals, vertices, idx, ext_xform, False)
    if int_xform is not None:
        for tri in triangles:
            for idx in (tri[0], tri[2], tri[1]):
                _emit_face(out, texcoords, normals, vertices, idx, int_xform, True)


# GLU domain-distance step per distance-LOD level (finest first). Level 0 keeps
# the pre-LOD default (30) so a close-up teapot is unchanged; coarser levels use
# fewer steps, so a far-off teapot tessellates into far fewer triangles.
LOD_STEPS = (30.0, 16.0, 8.0, 4.0)


def steps_for_level(level: int) -> float:
    return LOD_STEPS[min(level, len(LOD_STEPS) - 1)]


def tessellate_patches(patches: Any, sampling: Any = None, steps: Optional[float] = None,
                       ext_transforms: Any = None,
                       int_transforms: Any = None) -> np.ndarray:
    """Tessellate patches into a flat float32 T2F_N3F_V3F array.

    Must be called with a current GL context.  ``steps`` sets the GLU
    domain-distance U/V step directly (distance-LOD); when None the default
    sampling is used.  ``ext_transforms``/``int_transforms`` are per-patch
    atlas affines (parallel to ``patches``); when both are None the raw
    per-patch parametric (u, v) is used and no interior faces are emitted.
    """
    out: list[float] = []
    for i, indices in enumerate(patches):
        surface = _patch_surface(indices, sampling)
        callback = nurbs._tessellate_nurbs_surface(
            surface, sampling=sampling, u_step=steps, v_step=steps, texcoord=True)
        ext = ext_transforms[i] if ext_transforms is not None else (1.0, 1.0, 0.0, 0.0)
        interior = int_transforms[i] if int_transforms is not None else None
        _emit_patch(callback, out, ext, interior)
    return np.array(out, dtype=np.float32)


def tessellate_teapot(sampling: Any = None, steps: Optional[float] = None,
                      interior: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Tessellate the whole teapot into injectively textured T2F_N3F_V3F arrays.

    Returns a ``(base, lid)`` pair of flat float32 arrays.  The lid is kept
    separate so it can be drawn or skipped without re-tessellating.  ``steps``
    selects the GLU U/V step for distance-LOD (see ``steps_for_level``).  When
    ``interior`` is True each patch also emits reversed interior faces mapped to
    the interior half of the injective atlas (see :func:`injective_uv_transforms`).
    """
    base_ext, base_int, lid_ext, lid_int = injective_uv_transforms()
    base_int_arg: Any = None if not interior else base_int
    lid_int_arg: Any = None if not interior else lid_int
    base_patches: list[Any] = []
    for part in PART_ORDER:
        base_patches.extend(PATCH_GROUPS[part])
    base = tessellate_patches(base_patches, sampling, steps, base_ext, base_int_arg)
    lid = tessellate_patches(PATCH_GROUPS[LID_PART], sampling, steps, lid_ext, lid_int_arg)
    log.debug(
        "Teapot tessellated: %d base vertices, %d lid vertices",
        len(base) // FLOATS_PER_VERTEX,
        len(lid) // FLOATS_PER_VERTEX,
    )
    return base, lid


def compute_tangents(interleaved: Any) -> np.ndarray:
    """Per-vertex tangents (vec4, w=handedness) for a T2F_N3F_V3F triangle soup.

    Tangent-space normal (bump) mapping needs, per vertex, the surface direction
    along the texture's u axis.  This derives it from each triangle's position and
    UV gradients (Lengyel's method), orthogonalises against the vertex normal, and
    assigns the flat per-triangle tangent to its three vertices (the teapot mesh is
    a triangle soup, so there is nothing to average across).  Interior faces feed
    their own reversed positions/UVs, so their tangents come out consistent too.

    Returns an ``(N, 4)`` float32 array parallel to the vertices; w is +1 (the
    arare bump pattern is symmetric, so handedness sign is not significant).
    """
    v = np.asarray(interleaved, dtype=np.float32).reshape(-1, FLOATS_PER_VERTEX)
    n = len(v)
    tangents = np.zeros((n, 4), dtype=np.float32)
    if n == 0:
        return tangents
    tri = v.reshape(-1, 3, FLOATS_PER_VERTEX)
    p0, p1, p2 = tri[:, 0, 5:8], tri[:, 1, 5:8], tri[:, 2, 5:8]
    w0, w1, w2 = tri[:, 0, 0:2], tri[:, 1, 0:2], tri[:, 2, 0:2]
    e1, e2 = p1 - p0, p2 - p0
    du1, du2 = w1 - w0, w2 - w0
    denom = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]
    f = np.where(np.abs(denom) > 1e-8, 1.0 / np.where(denom == 0, 1.0, denom), 0.0)
    t = (e1 * du2[:, 1, None] - e2 * du1[:, 1, None]) * f[:, None]
    t = np.repeat(t, 3, axis=0)                       # flat tangent per vertex
    normals = v[:, 2:5]
    t -= np.sum(t * normals, axis=1, keepdims=True) * normals   # Gram-Schmidt
    length = np.linalg.norm(t, axis=1, keepdims=True)
    tangents[:, 0:3] = np.where(length > 1e-8, t / np.where(length == 0, 1.0, length), 0.0)
    tangents[:, 3] = 1.0
    return tangents
