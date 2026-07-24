"""Distance-based level-of-detail for procedurally tessellated geometry.

This is distinct from the VRML97 LOD node (:mod:`OpenGLContext.scenegraph.lod`),
which switches between author-provided child nodes by camera range. Here a single
procedural mesh (a teapot, a quadric, a NURBS surface) picks its *tessellation
resolution* from how far the camera is, so an object that is far away is built --
and cached -- at a much coarser resolution than one that is close, without the
author having to supply multiple models.

A geometry node calls :func:`lod_level` with its local-space bounding-sphere
centre and radius; it gets back an integer level (0 = finest) which it uses both
to choose a resolution and to key its per-level mesh cache.

The metric is deliberately simple (the user's call): the eye-space distance from
the camera to the object centre, divided by the object's radius -- i.e. "how many
radii away is the camera". Dividing by the radius makes it scale-invariant, so a
huge sphere and a tiny one behave the same way at proportional distances. No
projection or viewport is consulted.

Disable with ``OPENGLCONTEXT_LOD=off`` (deterministic output, e.g. for
reference-image regression) or per node via a ``lod=False`` field.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import numpy as np

# Distance thresholds in object-radii. The camera being closer than
# thresholds[i] selects level i; past the last threshold the coarsest level
# (len(thresholds)) is used. Four levels: 0 (finest) .. 3 (coarsest).
#
# Tuned against measured on-screen "pop" (test_lod_transitions): each boundary is
# placed far enough out that switching to the next-coarser mesh changes < ~1% of
# the frame. The first switch is the tightest (full -> level 1 is the biggest mesh
# jump), which is why level 0 is held out to 14 radii; the later switches pop far
# less, so those thresholds sit where the coarser mesh is essentially free.
DEFAULT_THRESHOLDS = (14.0, 26.0, 50.0)
COARSEST_LEVEL = len(DEFAULT_THRESHOLDS)

_TINY = 1e-6


def lod_enabled() -> bool:
    """Whether distance LOD is active (env kill-switch for deterministic output)."""
    return os.environ.get('OPENGLCONTEXT_LOD', '').strip().lower() not in (
        '0', 'off', 'false', 'no', 'none',
    )


def camera_distance_radii(center_local: Any, radius_local: float, modelview: Any) -> float:
    """Eye-space camera distance to ``center_local``, in units of ``radius_local``.

    The modelview maps local space to eye space, where the camera sits at the
    origin, so the distance is just the length of the transformed centre. Row-
    vector convention (``point @ modelview``), matching the rest of the pass.
    """
    mv = np.asarray(modelview, dtype='d')
    c = np.array([center_local[0], center_local[1], center_local[2], 1.0], dtype='d') @ mv
    dist = float(np.linalg.norm(c[:3]))
    return dist / max(float(radius_local), _TINY)


def level_from_distance(distance_radii: float, thresholds: Sequence[float] = DEFAULT_THRESHOLDS) -> int:
    """Map a normalized camera distance to an LOD level (0 = finest)."""
    for i, t in enumerate(thresholds):
        if distance_radii < t:
            return i
    return len(thresholds)


def lod_level(mode: Any, center_local: Any, radius_local: float,
              thresholds: Sequence[float] = DEFAULT_THRESHOLDS) -> int:
    """LOD level (0 = finest) for a mesh at this frame, size-normalized.

    Returns 0 (finest) when LOD is disabled or the distance can't be determined,
    so the result is never *coarser* than the caller would otherwise draw.
    """
    if not lod_enabled():
        return 0
    matrix = getattr(mode, 'matrix', None)
    if matrix is None:
        return 0
    try:
        d = camera_distance_radii(center_local, radius_local, matrix)
    except Exception:
        return 0
    return level_from_distance(d, thresholds)
