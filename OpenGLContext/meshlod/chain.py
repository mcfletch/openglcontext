"""A run of progressively coarser versions of one mesh.

Each level halves the triangle count of the one before it by default, which is
the schedule a distance-driven level of detail wants: every step out doubles the
area one triangle covers, so halving keeps the on-screen triangle density
roughly constant.

The whole reduction is decimated **once**. ``opengl_decimate`` records the
ordered contractions and every level is a prefix of that record, so building
five levels costs one reduction rather than five, and asking for a sixth
afterwards costs nothing.

    from OpenGLContext.meshlod import build_chain

    chain = build_chain(attributes, indices, levels=5)
    chain[0].triangle_count        # the mesh as it arrived
    chain[3].attributes            # an eighth of the triangles
    chain[3].error                 # how far that has moved, in model units
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

__all__ = ["LODLevel", "LODChain", "build_chain"]


@dataclass(frozen=True)
class LODLevel:
    """One rung: the arrays to draw, and what they cost in accuracy."""

    attributes: dict[str, np.ndarray]
    indices: np.ndarray
    #: Deviation from the mesh that was handed in, in model units. Measured by
    #: sampling both surfaces rather than taken from the quadrics, since a
    #: quadric measures distance to planes and drifts optimistic.
    error: float
    #: For every vertex of the *original* mesh, the vertex here it became. The
    #: correspondence a geomorph needs to lerp one level toward the next.
    vertex_map: np.ndarray

    @property
    def triangle_count(self) -> int:
        """Triangles at this level."""
        return len(self.indices) // 3

    @property
    def vertex_count(self) -> int:
        """Vertices at this level."""
        return len(self.attributes["POSITION"])


class LODChain(Sequence[LODLevel]):
    """The levels, finest first, and the size of what they describe.

    ``radius`` is the bounding-sphere radius of the original mesh. Every
    distance in :mod:`~OpenGLContext.meshlod.quality` is expressed in multiples
    of it, so a measurement of a bust and a measurement of a cliff can be
    compared and a switching schedule is scale free.
    """

    def __init__(self, levels: Sequence[LODLevel], centre: Any, radius: float) -> None:
        self._levels = tuple(levels)
        self.centre = np.asarray(centre, dtype="d")
        self.radius = float(radius)

    def __len__(self) -> int:
        return len(self._levels)

    def __getitem__(self, index: Any) -> Any:
        return self._levels[index]

    def __repr__(self) -> str:
        counts = ", ".join(str(level.triangle_count) for level in self._levels)
        return "<LODChain %s triangles>" % (counts,)


def bounding_sphere(positions: Any) -> tuple[Any, float]:
    """Centre and radius of a sphere holding every point.

    The centre of the bounding box rather than of the points, so a dense patch
    on one side of a model does not drag the centre into it and leave the
    silhouette lopsided in the measurements.
    """
    points = np.asarray(positions, dtype="d")
    if not len(points):
        return np.zeros(3), 0.0
    centre = 0.5 * (points.max(axis=0) + points.min(axis=0))
    return centre, float(np.max(np.linalg.norm(points - centre, axis=1)))


def build_chain(
    attributes: Any,
    indices: Any,
    levels: int = 5,
    ratio: float = 0.5,
    certify: bool = True,
    **options: Any,
) -> LODChain:
    """Decimate ``attributes``/``indices`` into ``levels`` rungs.

    Level 0 is the mesh as it arrived. Each further level has ``ratio`` of the
    triangles of the one before. A level that cannot be reached -- an open
    surface cannot be reduced past its own borders -- stops the chain there
    rather than repeating the last rung.

    ``certify`` measures each level against the original by sampling both
    surfaces. It is on by default because an unmeasured level cannot be given a
    switching distance; pass ``False`` where only the geometry is wanted.
    Further keyword arguments go to ``opengl_decimate.SimplifyOptions``.
    """
    from opengl_decimate import SimplifyOptions, certify as certification, collapse_sequence

    positions = np.asarray(attributes["POSITION"])
    centre, radius = bounding_sphere(positions)
    original = len(np.asarray(indices).reshape(-1)) // 3

    # Each surviving corner keeps the normal it arrived with, rather than taking
    # one from the coarser surface. A carried normal still points the way the
    # *fine* surface did, so a flat triangle shades like the curve it replaced --
    # which is what a baked normal map buys, at no cost and with no texture.
    #
    # Measured on a 17k-triangle bust, as the share of the object's pixels that
    # shade differently from the original, over distances from touching to far:
    #
    #     level        carried        recomputed
    #     8728 tris    3.0 - 6.6%     9.0 - 14.0%
    #     4364 tris   11.9 - 14.6%   19.5 - 24.3%
    #     2182 tris   21.8 - 24.5%   29.3 - 33.1%
    #
    # The outline is identical either way, since normals do not move a vertex.
    # `recompute_normals=True` is still worth having where the input's normals
    # are wrong or absent.
    options.setdefault("recompute_normals", False)
    sequence = collapse_sequence(
        attributes, indices, SimplifyOptions(target_ratio=ratio, **options)
    )

    built = [
        LODLevel(
            attributes={name: np.asarray(value).copy() for name, value in attributes.items()},
            indices=np.ascontiguousarray(indices, dtype=np.uint32).reshape(-1),
            error=0.0,
            vertex_map=np.arange(len(positions), dtype=np.int64),
        )
    ]
    wanted = original
    for _step in range(1, levels):
        wanted = int(wanted * ratio)
        if wanted < 4:
            break
        result = sequence.at(target_count=wanted)
        if result.triangle_count >= built[-1].triangle_count:
            # The reduction has run out of legal contractions; another rung
            # would be a copy of the last one.
            break
        error = result.error
        if certify:
            error = certification.surface_deviation(
                positions,
                indices,
                result.attributes["POSITION"],
                result.indices,
                samples=4000,
            ).max
        built.append(
            LODLevel(
                attributes=result.attributes,
                indices=result.indices,
                error=float(error),
                vertex_map=result.vertex_map,
            )
        )
    return LODChain(built, centre, radius)
