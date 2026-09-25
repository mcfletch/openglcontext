"""Zones as gravity volumes: the ``OMI_physics_gravity`` a zone carries.

A :class:`~OpenGLContext.scenegraph.zone.ZoneGravity` setting is a gravity
volume whose region is its zone's shape. :func:`gravity_volumes` turns a
scene's zones into :class:`omi_physics.gravity.GravityVolume` records, which a
:class:`~omi_physics.world.PhysicsWorld` resolves for each body by its centre,
in ascending priority, with ``replace`` and ``stop`` as the extension defines
them. :func:`scene_zones` finds the zones in a scenegraph and places them, as
the scene is when it is asked; :class:`GravityZones` keeps a world's volumes
where the render pass places the zones each frame, so gravity follows a zone
that moves or is edited.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Sequence, Tuple

import numpy as np
from omi_physics import model
from omi_physics.gravity import GravityVolume

from OpenGLContext.scenegraph.zone import (
    GRAVITY, PlacedZone, Zone, ZoneGravity, placed_zones,
)
from OpenGLContext.scenegraph.zones import PlacedShape

__all__ = ['ZoneRegion', 'GravityZones', 'gravity_volumes', 'scene_zones']


class ZoneRegion:
    """A zone's shape, as the region of an ``omi_physics`` gravity volume."""

    def __init__(self, shape: PlacedShape) -> None:
        self.shape = shape

    def contains(self, pos: Any) -> bool:
        """Whether the world point ``pos`` is on or inside the shape."""
        return float(self.shape.distance(np.asarray(pos, dtype='d')[:3])) <= 0.0


def gravity_volumes(zones: Iterable[PlacedZone]) -> List[GravityVolume]:
    """A gravity volume for each zone whose gravity setting is enabled.

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
        field = model.Gravity(
            type=str(setting.type), gravity=float(setting.gravity),
            direction=tuple(float(v) for v in direction),
            center=tuple(float(v) for v in zone.to_world(setting.center)),
            priority=int(zone.priority), replace=bool(setting.replace),
            stop=bool(setting.stop))
        volumes.append(GravityVolume(field, ZoneRegion(zone.shape)))
    return volumes


def scene_zones(group: Any) -> List[PlacedZone]:
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


class GravityZones:
    """A physics world's gravity volumes from zones, kept where the zones are.

    :meth:`follow` is given the zones as they are placed now -- the render
    pass's ``zones``, each frame -- and, where the zones carrying gravity are
    other placements than last time, replaces every volume in the world whose
    region is a :class:`ZoneRegion` with volumes made from them. A zone that
    moves, or whose gravity setting is edited, has a new placement. Volumes
    the application added itself are left as they are.
    """

    def __init__(self, world: Any) -> None:
        self.world = world
        self._placed: Tuple[PlacedZone, ...] = ()

    def follow(self, zones: Sequence[PlacedZone]) -> bool:
        """Bring the world's zone volumes to ``zones``; return whether they changed."""
        placed = tuple(zone for zone in zones if zone.setting(GRAVITY) is not None)
        if len(placed) == len(self._placed) and all(
                one is other for one, other in zip(placed, self._placed, strict=True)):
            return False
        self._placed = placed
        kept = [volume for volume in self.world.gravity_volumes
                if not isinstance(getattr(volume, 'region', None), ZoneRegion)]
        self.world.gravity_volumes[:] = kept + gravity_volumes(placed)
        return True
