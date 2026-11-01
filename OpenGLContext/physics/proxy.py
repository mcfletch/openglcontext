"""Proxy: the shape that stands for a node in the physics world.

A :class:`Proxy` is a kind of shape and its parameters, with an identity, so
many bodies can share one cooked shape and the world holds it once.
:meth:`Proxy.from_node` cooks one from the triangles a node draws, by a strategy
name: ``'sphere'`` and ``'box'`` fit a primitive to the bounds, ``'convex'``
takes the hull, ``'trimesh'`` keeps the triangles (static bodies only), and
``'auto'`` is the triangles for a static body and the hull for a dynamic one.

The kinds, and the parameters each has (lengths in metres):

``box``
    ``size``, the full extents ``(x, y, z)``.
``sphere``
    ``radius``.
``capsule``
    ``height``, the length of the straight middle, and ``radius``.
``cylinder``
    ``height``, end to end, ``radius`` at the bottom and ``radius_top``.
``convex``
    ``points``, an ``(n, 3)`` array whose hull is the shape.
``trimesh``
    ``points`` and ``indices``, ``(t, 3)`` triangles; static bodies only.
``compound``
    ``parts``, each ``(proxy, position, orientation)`` in the body's frame,
    the orientation a quaternion ``(x, y, z, w)``.
``heightfield``
    The arguments of :meth:`Proxy.heightfield`.
"""
from __future__ import annotations

import itertools
import math
import types
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import numpy as np

__all__ = ['DEFAULT_DENSITY', 'KINDS', 'STRATEGIES', 'Proxy']

#: Kilograms a cubic metre of a body weighs when the application names no mass.
DEFAULT_DENSITY = 500.0
#: The strategy names :meth:`Proxy.from_node` accepts.
STRATEGIES = ('auto', 'sphere', 'box', 'convex', 'trimesh')
#: The kinds of shape a proxy is.
KINDS = ('box', 'sphere', 'capsule', 'cylinder', 'convex', 'trimesh', 'compound', 'heightfield')

_ids = itertools.count(1)


class Proxy:
    """A collision shape, shared by every body made with it."""

    def __init__(self, kind: str, params: Mapping[str, Any] | None = None) -> None:
        if kind not in KINDS:
            raise ValueError('unknown proxy kind %r; choose from %s' % (kind, ', '.join(KINDS)))
        #: Distinguishes this proxy from every other for as long as the process runs.
        self.uid = next(_ids)
        #: One of :data:`KINDS`.
        self.kind = kind
        #: The shape's parameters by name, as the module's table gives them; read-only.
        self.params: Mapping[str, Any] = types.MappingProxyType(dict(params or {}))
        #: The engine's own shape, made by the engine adapter on first use.
        self._engine_shape: Any = None

    def __repr__(self) -> str:
        return 'Proxy(%s, uid=%d)' % (self.kind, self.uid)

    # -- by hand --------------------------------------------------------
    @classmethod
    def box(cls, size: Iterable[float] = (1.0, 1.0, 1.0)) -> Proxy:
        """A box of full extents ``size``."""
        return cls('box', {'size': tuple(float(v) for v in size)})

    @classmethod
    def sphere(cls, radius: float = 0.5) -> Proxy:
        """A sphere of ``radius``."""
        return cls('sphere', {'radius': float(radius)})

    @classmethod
    def capsule(cls, height: float = 1.0, radius: float = 0.5) -> Proxy:
        """A capsule whose straight middle is ``height`` long."""
        return cls('capsule', {'height': float(height), 'radius': float(radius)})

    @classmethod
    def cylinder(cls, height: float = 2.0, radius: float = 0.5,
                 radius_top: float | None = None) -> Proxy:
        """A cylinder ``height`` long end to end; ``radius_top`` narrows its top (0 is a cone)."""
        return cls('cylinder', {'height': float(height), 'radius': float(radius),
                                'radius_top': float(radius if radius_top is None else radius_top)})

    @classmethod
    def convex(cls, points: Any) -> Proxy:
        """The convex hull of ``points``, an ``(n, 3)`` array."""
        return cls('convex', {'points': np.asarray(points, dtype='d')})

    @classmethod
    def trimesh(cls, points: Any, indices: Any) -> Proxy:
        """A static triangle mesh from vertices and ``(t, 3)`` triangle indices."""
        return cls('trimesh', {'points': np.asarray(points, dtype='d'),
                               'indices': np.asarray(indices, dtype='i')})

    @classmethod
    def compound(cls, parts: Iterable[tuple[Proxy, Iterable[float], Iterable[float]]]) -> Proxy:
        """Several proxies held in one body, each ``(proxy, position, orientation)`` in its frame."""
        return cls('compound', {'parts': tuple(
            (part, tuple(float(v) for v in position), tuple(float(v) for v in orientation))
            for part, position, orientation in parts)})

    @classmethod
    def heightfield(cls, heights: Any = None, origin: Iterable[float] = (0.0, 0.0, 0.0),
                    spacing: Any = 1.0, *, sample: Callable[..., Any] | None = None,
                    normal: Callable[..., Any] | None = None, extent: Any = None,
                    vectorized: bool = False, height_range: Any = None,
                    feature: float = 1.0) -> Proxy:
        """Static ground that answers a height at each ``(x, z)``: a grid of ``heights``, or ``sample`` a function.

        ``heights[j, i]`` is the height at ``x = origin[0] + i * spacing``,
        ``z = origin[2] + j * spacing``, added to ``origin[1]``; ``spacing``
        is one number or ``(along x, along z)``. ``sample(x, z)`` answers the
        height, given arrays where ``vectorized``; ``normal(x, z)`` the unit
        normal, else the slope of ``sample``. ``extent`` is ``((x_min, z_min),
        (x_max, z_max))`` or None for land without an edge, ``height_range``
        ``(lowest, highest)``, and ``feature`` the horizontal distance over
        which the land changes appreciably. Everything below the surface is solid.
        """
        if (heights is None) == (sample is None):
            raise ValueError('a heightfield is given heights or a sample function, not both '
                             'and not neither')
        params: dict[str, Any]
        if heights is not None:
            params = {'heights': np.asarray(heights, dtype='d'), 'origin': tuple(origin),
                      'spacing': spacing}
        else:
            params = {'sample': sample, 'normal': normal, 'extent': extent,
                      'vectorized': bool(vectorized), 'height_range': height_range,
                      'feature': float(feature)}
        return cls('heightfield', params)

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
        if strategy == 'auto' and dynamic:
            exact = _exact_primitive(points)
            if exact is not None:
                return exact
        from OpenGLContext.physics.cooking import cook  # noqa: PLC0415 cooking imports this module

        return cook(points, indices, strategy, dynamic)

    # -- measures -------------------------------------------------------
    def volume(self) -> float:
        """The volume of the shape in cubic metres; a mesh is measured by its bounds."""
        params = self.params
        if self.kind == 'box':
            return float(np.prod(params['size']))
        if self.kind == 'sphere':
            return 4.0 / 3.0 * math.pi * params['radius'] ** 3
        if self.kind == 'capsule':
            radius = params['radius']
            return math.pi * radius ** 2 * params['height'] + 4.0 / 3.0 * math.pi * radius ** 3
        if self.kind == 'cylinder':
            return (math.pi * (params['radius'] + params['radius_top']) ** 2 / 4.0
                    * params['height'])
        if self.kind == 'compound':
            return sum(part.volume() for part, _position, _orientation in params['parts'])
        points = params.get('points')
        if points is None or len(points) == 0:
            return 0.0
        if self.kind == 'convex':
            from OpenGLContext.physics.cooking import points_hull_volume  # noqa: PLC0415 cooking imports this module

            return points_hull_volume(points)
        return float(np.prod(points.max(axis=0) - points.min(axis=0)))

    def mass(self, density: float = DEFAULT_DENSITY) -> float:
        """The mass of the shape at ``density`` kilograms a cubic metre, at least 0.001."""
        return max(self.volume() * float(density), 0.001)


def _exact_primitive(points: np.ndarray) -> Proxy | None:
    """A box or a sphere the vertices are exactly, else None.

    A box mesh has every vertex at a corner of its bounds. A sphere mesh has
    every vertex the same distance from the middle of its bounds, and bounds as
    wide as they are tall and deep.
    """
    lo, hi = points.min(axis=0), points.max(axis=0)
    size = hi - lo
    if not np.all(size > 1e-9):
        return None
    scale = float(size.max())
    unit = (points - lo) / size
    if np.all(np.minimum(unit, 1.0 - unit) < 1e-6):
        return Proxy.box(tuple(size))
    middle = (lo + hi) / 2.0
    radii = np.linalg.norm(points - middle, axis=1)
    if (np.ptp(size) < 0.02 * scale and np.ptp(radii) < 0.02 * scale
            and abs(radii.mean() - scale / 2.0) < 0.02 * scale):
        return Proxy.sphere(float(radii.mean()))
    return None
