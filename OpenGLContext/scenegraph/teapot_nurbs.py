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

# Floats per interleaved N3F_V3F vertex (normal, then position).
FLOATS_PER_VERTEX = 6


def _orient(point):
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


def _patch_surface(indices, sampling):
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


def _accumulate_triangles(callback, out):
    """Append a callback's triangles to ``out`` as flat N3F_V3F floats."""
    vertices = callback.vertices
    normals = callback.normals
    for tri in callback.build_triangles():
        for idx in tri:
            normal = normals[idx] if idx < len(normals) else (0.0, 0.0, 1.0)
            out.extend(normal)
            out.extend(vertices[idx])


def tessellate_patches(patches, sampling=None):
    """Tessellate a list of patches into a flat float32 N3F_V3F array.

    Must be called with a current GL context.
    """
    out = []
    for indices in patches:
        surface = _patch_surface(indices, sampling)
        callback = nurbs._tessellate_nurbs_surface(surface, sampling=sampling)
        _accumulate_triangles(callback, out)
    return np.array(out, dtype=np.float32)


def tessellate_teapot(sampling=None):
    """Tessellate the whole teapot.

    Returns a ``(base, lid)`` pair of flat float32 N3F_V3F arrays.  The lid is
    kept separate so it can be drawn or skipped without re-tessellating.
    """
    base_patches = []
    for part in PART_ORDER:
        base_patches.extend(PATCH_GROUPS[part])
    base = tessellate_patches(base_patches, sampling)
    lid = tessellate_patches(PATCH_GROUPS[LID_PART], sampling)
    log.debug(
        "Teapot tessellated: %d base vertices, %d lid vertices",
        len(base) // FLOATS_PER_VERTEX,
        len(lid) // FLOATS_PER_VERTEX,
    )
    return base, lid
