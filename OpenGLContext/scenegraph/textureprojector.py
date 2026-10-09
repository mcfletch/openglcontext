"""X3D's TextureProjection: a picture cast onto the surfaces in front of it -- no GL

A ``TextureProjector`` casts its ``texture`` from ``location`` along
``direction`` through a perspective of ``fieldOfView`` (the smaller of the
picture's two angles, the other following the picture's proportions); a
``TextureProjectorParallel`` casts it straight along ``direction`` across the
rectangle ``fieldOfView`` gives (minimum x, minimum y, maximum x, maximum y),
like a slide in sunlight. ``upVector`` turns the picture about the direction.
``nearDistance`` and ``farDistance``, where positive, bound how far along the
direction it reaches; -1 is no bound.

Where it falls, a projector modulates the surface's diffuse colour (base
colour, emissive colour for an unlit surface) by its texture's colour times
its ``color``, weighted by the texel's alpha times ``intensity``, as X3D
browsers draw it, on the faces turned toward it
(``shaders/_projectors_inc.glsl``). Its ``global`` and scope are a light's
(:mod:`OpenGLContext.passes.lightscope`). The ``shadows`` field is kept and
not acted on: the picture falls on every surface in front of the projector.

:func:`projector_matrix` is where a projector maps a world point; the pass
gives it to the shaders (:mod:`OpenGLContext.passes.projectorpass`).
"""
from __future__ import annotations

import math
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml.x3d import nodes as x3d

from OpenGLContext.passes import shadowmath

__all__ = ['FAR', 'NEAR', 'Projection', 'TextureProjector', 'TextureProjectorParallel',
           'is_projector', 'projector_matrix']

#: The planes a projector with no near or far bound is drawn between.
NEAR = 1e-3
FAR = 1e5


def is_projector(node: Any) -> bool:
    """Whether a light node is a texture projector rather than a light"""
    return isinstance(node, x3d.X3DTextureProjectorNode)


class Projection(NamedTuple):
    """Where a projector casts, in world space"""

    #: World to clip space, row vectors: a point's clip coordinates are
    #: ``(x, y, z, 1) @ matrix``.
    matrix: np.ndarray
    #: Where it casts from (a perspective projector), in the world.
    location: tuple[float, float, float]
    #: The direction it casts along, in the world.
    direction: tuple[float, float, float]
    #: Whether its near and its far distances bound it.
    bounded: tuple[bool, bool]
    perspective: bool


def _unit(vector: Any) -> np.ndarray:
    found = np.asarray(vector, np.float64)[:3]
    length = float(np.linalg.norm(found))
    return found / length if length > 1e-12 else np.array([0.0, 0.0, 1.0])


def projector_matrix(projector: Any, world: Any = None,
                     aspect: float = 1.0) -> Optional[Projection]:
    """Where ``projector`` casts under the row-vector ``world`` matrix; None where it cannot

    ``aspect`` is the picture's width over its height.
    """
    world = np.identity(4) if world is None else np.asarray(world, np.float64)
    place = np.append(np.asarray(projector.location, np.float64)[:3], 1.0) @ world
    location = place[:3] / (place[3] or 1.0)
    direction = _unit(np.append(_unit(projector.direction), 0.0) @ world)
    up = _unit(np.append(_unit(projector.upVector), 0.0) @ world)
    near = float(projector.nearDistance)
    far = float(projector.farDistance)
    bounded = (near > 0.0, far > 0.0)
    near = near if bounded[0] else NEAR
    far = far if bounded[1] and far > near else (FAR if not bounded[1] else near * 2.0)
    view = shadowmath.look_at_matrix(tuple(location), tuple(direction), tuple(up))
    aspect = aspect if aspect > 0 and math.isfinite(aspect) else 1.0
    if isinstance(projector, x3d.TextureProjectorParallel):
        left, bottom, right, top = (float(value) for value in projector.fieldOfView)
        if right <= left or top <= bottom:
            return None
        projection = _orthographic(left, right, bottom, top, near, far)
        perspective = False
    else:
        angle = float(projector.fieldOfView)
        if not 0.0 < angle < math.pi:
            return None
        # The field of view is the smaller of the two angles.
        if aspect >= 1.0:
            fovy = angle
        else:
            fovy = 2.0 * math.atan(math.tan(angle / 2.0) / aspect)
        projection = np.asarray(shadowmath.perspective_matrix(fovy, aspect, near, far),
                                np.float64)
        perspective = True
    matrix = np.asarray(view, np.float64) @ projection
    return Projection(matrix.astype(np.float32),
                      (float(location[0]), float(location[1]), float(location[2])),
                      (float(direction[0]), float(direction[1]), float(direction[2])),
                      bounded, perspective)


def _orthographic(left: float, right: float, bottom: float, top: float,
                  near: float, far: float) -> np.ndarray:
    """A row-vector orthographic projection"""
    matrix = np.identity(4)
    matrix[0, 0] = 2.0 / (right - left)
    matrix[1, 1] = 2.0 / (top - bottom)
    matrix[2, 2] = -2.0 / (far - near)
    matrix[3, 0] = -(right + left) / (right - left)
    matrix[3, 1] = -(top + bottom) / (top - bottom)
    matrix[3, 2] = -(far + near) / (far - near)
    return matrix


class TextureProjector(x3d.TextureProjector):
    """X3D's TextureProjector: a picture cast through a perspective"""


class TextureProjectorParallel(x3d.TextureProjectorParallel):
    """X3D's TextureProjectorParallel: a picture cast straight along its direction"""
