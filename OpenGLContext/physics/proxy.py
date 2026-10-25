"""Proxy: the shape that stands for a node in the physics world.

A :class:`Proxy` wraps an :class:`omi_physics.model.Shape` and gives it an
identity, so many bodies can share one cooked shape and the world holds it once.
:meth:`Proxy.from_node` cooks one from the triangles a node draws, by a strategy
name: ``'sphere'`` and ``'box'`` fit a primitive to the bounds, ``'convex'``
takes the hull, ``'trimesh'`` keeps the triangles (static bodies only), and
``'auto'`` is the triangles for a static body and the hull for a dynamic one.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from typing import Any

import numpy as np
from omi_physics import cookery, hull, model

__all__ = ['DEFAULT_DENSITY', 'STRATEGIES', 'Proxy']

#: Kilograms a cubic metre of a body weighs when the application names no mass.
DEFAULT_DENSITY = 500.0
#: The strategy names :meth:`Proxy.from_node` accepts.
STRATEGIES = ('auto', 'sphere', 'box', 'convex', 'trimesh')

_ids = itertools.count(1)


class Proxy:
    """A collision shape, shared by every body made with it."""

    def __init__(self, shape: model.Shape) -> None:
        #: Distinguishes this proxy from every other for as long as the process runs.
        self.uid = next(_ids)
        self.shape = shape

    def __repr__(self) -> str:
        return 'Proxy(%s, uid=%d)' % (self.shape.type, self.uid)

    # -- by hand --------------------------------------------------------
    @classmethod
    def box(cls, size: Iterable[float] = (1.0, 1.0, 1.0)) -> Proxy:
        """A box of full extents ``size``."""
        return cls(model.Shape.box(tuple(float(v) for v in size)))

    @classmethod
    def sphere(cls, radius: float = 0.5) -> Proxy:
        """A sphere of ``radius``."""
        return cls(model.Shape.sphere(radius))

    @classmethod
    def capsule(cls, height: float = 1.0, radius: float = 0.5) -> Proxy:
        """A capsule whose straight middle is ``height`` long."""
        return cls(model.Shape.capsule(height, radius))

    @classmethod
    def cylinder(cls, height: float = 2.0, radius: float = 0.5) -> Proxy:
        """A cylinder ``height`` long end to end."""
        return cls(model.Shape.cylinder(height, radius))

    @classmethod
    def convex(cls, points: Any) -> Proxy:
        """The convex hull of ``points``, an ``(n, 3)`` array."""
        return cls(model.Shape.convex(points))

    @classmethod
    def trimesh(cls, points: Any, indices: Any) -> Proxy:
        """A static triangle mesh from vertices and ``(t, 3)`` triangle indices."""
        return cls(model.Shape.trimesh(points, indices))

    # -- from what is drawn ---------------------------------------------
    @classmethod
    def from_node(cls, node: Any, strategy: str = 'auto', dynamic: bool = True) -> Proxy:
        """Cook a proxy from the triangles ``node`` draws.

        Raises ValueError for an unknown ``strategy``, for a node that draws no
        triangles, and for ``'trimesh'`` on a dynamic body.
        """
        if strategy not in STRATEGIES:
            raise ValueError('unknown proxy strategy %r; choose from %s'
                             % (strategy, ', '.join(STRATEGIES)))
        from OpenGLContext.physics.gltf_world import node_mesh  # noqa: PLC0415 gltf_world imports the scenegraph

        found = node_mesh(node)
        if found is None:
            raise ValueError('%r draws no triangles to make a collision shape from' % (node,))
        points, indices = found
        return cls.from_mesh(points, indices, strategy, dynamic)

    @classmethod
    def from_mesh(cls, points: np.ndarray, indices: np.ndarray | None,
                  strategy: str = 'auto', dynamic: bool = True) -> Proxy:
        """Cook a proxy from vertices and triangles, as :meth:`from_node` does."""
        if strategy not in STRATEGIES:
            raise ValueError('unknown proxy strategy %r; choose from %s'
                             % (strategy, ', '.join(STRATEGIES)))
        if strategy == 'trimesh' and dynamic:
            raise ValueError("a dynamic body cannot use 'trimesh'; use 'convex' or 'auto'")
        points = np.asarray(points, dtype='d')
        if strategy in ('sphere', 'box'):
            lo, hi = points.min(axis=0), points.max(axis=0)
            if strategy == 'sphere':
                return cls.sphere(float((hi - lo).max()) / 2.0)
            return cls.box(tuple(hi - lo))
        cooked = cookery.cook_shape(points, indices, 'convex' if strategy == 'convex' else 'auto',
                                    dynamic)
        if isinstance(cooked, list):
            return cls(model.Shape.compound([(piece, (0.0, 0.0, 0.0)) for piece in cooked]))
        return cls(cooked)

    # -- measures -------------------------------------------------------
    def volume(self) -> float:
        """The volume of the shape in cubic metres; a mesh is measured by its bounds."""
        shape = self.shape
        if shape.type == 'box':
            return float(np.prod(shape.size))
        if shape.type == 'sphere':
            return 4.0 / 3.0 * math.pi * shape.radius ** 3
        if shape.type == 'capsule':
            radius = shape.radiusBottom
            return math.pi * radius ** 2 * shape.height + 4.0 / 3.0 * math.pi * radius ** 3
        if shape.type == 'cylinder':
            return math.pi * (shape.radiusBottom + shape.radiusTop) ** 2 / 4.0 * shape.height
        if shape.type == 'compound' and shape.parts:
            return sum(Proxy(part.shape).volume() for part in shape.parts)
        points = shape.points
        if points is None or len(points) == 0:
            return 0.0
        if shape.type == 'convex':
            return _hull_volume(points)
        return float(np.prod(points.max(axis=0) - points.min(axis=0)))

    def mass(self, density: float = DEFAULT_DENSITY) -> float:
        """The mass of the shape at ``density`` kilograms a cubic metre, at least 0.001."""
        return max(self.volume() * float(density), 0.001)


def _hull_volume(points: np.ndarray) -> float:
    """The volume of the convex hull of ``points``, from tetrahedra to its centroid."""
    vertices, faces = hull.convex_hull(points)
    if len(faces) == 0:
        return float(np.prod(np.maximum(points.max(axis=0) - points.min(axis=0), 1e-6)))
    centre = vertices.mean(axis=0)
    a = vertices[faces[:, 0]] - centre
    b = vertices[faces[:, 1]] - centre
    c = vertices[faces[:, 2]] - centre
    return float(abs(np.einsum('ij,ij->i', a, np.cross(b, c)).sum()) / 6.0)
