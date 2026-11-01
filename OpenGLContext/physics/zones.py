"""Gravity regions, and zones as gravity volumes: the ``OMI_physics_gravity`` a zone carries.

:class:`Box` and :class:`Sphere` are the regions
:meth:`~OpenGLContext.physics.service.Physics.add_gravity_zone` takes. A
:class:`~OpenGLContext.scenegraph.zone.ZoneGravity` setting is a gravity
volume whose region is its zone's shape. :func:`gravity_zones` turns a scene's
zones into :class:`~OpenGLContext.physics.types.GravityZone` records, which the
world resolves for each body by its centre, in ascending priority, with
``replace`` and ``stop`` as the extension defines them. :func:`scene_zones`
finds the zones in a scenegraph and places them, as the scene is when it is
asked. :meth:`Physics.zones_changed
<OpenGLContext.physics.service.Physics.zones_changed>` takes the zones the
render pass places each frame, so gravity follows a zone that moves or is
edited.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
from OpenGLContext.scenegraph.zone import (
    GRAVITY, PlacedZone, Zone, ZoneGravity, placed_zones,
)
from OpenGLContext.physics.types import GravityZone
from OpenGLContext.scenegraph.zones import PlacedShape

__all__ = ['Box', 'Sphere', 'ZoneRegion', 'gravity_zones', 'scene_zones']


class ZoneRegion:
    """A zone's shape, as the region of a gravity volume."""

    def __init__(self, shape: PlacedShape) -> None:
        self.shape = shape

    def contains(self, pos: Any) -> bool:
        """Whether the world point ``pos`` is on or inside the shape."""
        return float(self.shape.distance(np.asarray(pos, dtype='d')[:3])) <= 0.0


def gravity_zones(zones: Iterable[PlacedZone]) -> list[GravityZone]:
    """A gravity zone for each zone whose gravity setting is enabled, its region the zone's shape.

    A directional field's ``direction`` and a point field's ``center`` are in
    the zone's own frame, so a turned zone turns its gravity with it. The
    volume's priority is the zone's.
    """
    volumes = []
    for zone in zones:
        setting = zone.setting(GRAVITY)
        if not isinstance(setting, ZoneGravity) or not bool(setting.enabled):
            continue
        rotation = zone.matrix[:3, :3]
        direction = np.asarray(setting.direction, dtype='d') @ rotation
        length = float(np.linalg.norm(direction))
        if length > 1e-12:
            direction = direction / length
        point = str(setting.type) == 'point'
        volumes.append(GravityZone(
            ZoneRegion(zone.shape), float(setting.gravity),
            (float(direction[0]), float(direction[1]), float(direction[2])),
            tuple(float(v) for v in zone.to_world(setting.center)) if point else None,
            int(zone.priority), bool(setting.replace), bool(setting.stop)))
    return volumes


def scene_zones(group: Any) -> list[PlacedZone]:
    """Every zone under ``group``, placed by the transforms above it.

    The children followed are the ones a node draws
    (``renderedChildren``), as the render pass follows them: a ``Switch``'s
    chosen node, each of an LOD's levels.
    """
    from OpenGLContext.physics.gltf_world import _local_matrix
    found = []
    todo = [(group, np.identity(4))]
    while todo:
        node, parent = todo.pop()
        world = _local_matrix(node) @ parent
        if isinstance(node, Zone):
            found.append((node, world))
            continue
        rendered = getattr(node, 'renderedChildren', None)
        children = rendered() if rendered is not None else getattr(node, 'children', None)
        for child in children or ():
            todo.append((child, world))
    return placed_zones(found)


class Box:
    """A box-shaped gravity region, square to the world axes: every point within half of ``size`` of ``center``.

    Lengths are in metres.
    """

    def __init__(self, center: Any = (0.0, 0.0, 0.0), size: Any = (1.0, 1.0, 1.0)) -> None:
        self.center = np.asarray(center, dtype='d')[:3]
        self.size = np.asarray(size, dtype='d')[:3]
        self.half = 0.5 * self.size

    def __repr__(self) -> str:
        return 'Box(center=%s, size=%s)' % (self.center.tolist(), self.size.tolist())

    def contains(self, pos: Any) -> bool:
        """Whether the world point ``pos`` is on or inside the box."""
        return bool(np.all(np.abs(np.asarray(pos, dtype='d')[:3] - self.center) <= self.half))


class Sphere:
    """A ball-shaped gravity region: every point within ``radius`` metres of ``center``."""

    def __init__(self, center: Any = (0.0, 0.0, 0.0), radius: float = 1.0) -> None:
        self.center = np.asarray(center, dtype='d')[:3]
        self.radius = float(radius)

    def __repr__(self) -> str:
        return 'Sphere(center=%s, radius=%g)' % (self.center.tolist(), self.radius)

    def contains(self, pos: Any) -> bool:
        """Whether the world point ``pos`` is on or inside the ball."""
        offset = np.asarray(pos, dtype='d')[:3] - self.center
        return bool(np.dot(offset, offset) <= self.radius ** 2)
