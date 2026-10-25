"""Questions asked of a world on the calling thread: sweeps and overlaps.

These work over a :class:`~omi_physics.world.PhysicsWorld` that the calling
thread may read: the live world of an inline service, or the render thread's
:class:`~OpenGLContext.physics.replica.Replica`. Candidates are found by the
world's bounding boxes, so a query costs the bodies near it and not the scene.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import model
from omi_physics.body import SphereProxy, make_proxy, world_aabb
from omi_physics.collide import collide

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.physics.body import Body

__all__ = ['Hit', 'overlapping', 'sweep_sphere']

_IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])
#: How many halvings find where a swept sphere first touches.
_BISECTIONS = 14


@dataclass(frozen=True, slots=True)
class Hit:
    """What a ray met: the body, the point, the surface normal there and how far along it was.

    ``triangle`` is the number of the triangle struck, or -1 for a shape that
    has none. ``body`` is None for a body the service has no handle for.
    """
    body: Body | None
    point: np.ndarray
    normal: np.ndarray
    distance: float
    triangle: int


def _candidates(world: PhysicsWorld, lo: np.ndarray, hi: np.ndarray,
                skip: Collection[int]) -> list[int]:
    """Indices of the solid bodies whose box meets ``lo`` to ``hi``, minus ``skip``."""
    near = ((world.collider_shape >= 0) & np.all(world.aabb_max >= lo, axis=1)
            & np.all(world.aabb_min <= hi, axis=1))
    return [j for j in np.flatnonzero(near).tolist()
            if j not in skip and not world.is_sensor(j) and world.handle_of(world.ref(j)) is not None]


def _proxy(world: PhysicsWorld, index: int, cache: dict[int, Any]) -> Any:
    found = cache.get(index)
    if found is None:
        found = cache[index] = make_proxy(world.shapes[world.collider_shape[index]],
                                          world.position[index], world.orientation[index])
    return found


def sweep_sphere(world: PhysicsWorld, origin: Any, direction: Any, distance: float,
                 radius: float, skip: Collection[int] = ()) -> float | None:
    """How far a sphere of ``radius`` can travel from ``origin`` along ``direction``.

    Returns the distance at which it first touches a solid body, 0 where it
    starts in one, or None where it travels ``distance`` clear. The sphere is
    stepped by half its radius, so a wall thinner than that can be passed.
    """
    start = np.asarray(origin, dtype='d')
    heading = np.asarray(direction, dtype='d')
    length = float(np.linalg.norm(heading))
    if length == 0.0 or distance <= 0.0:
        return None
    heading = heading / length
    end = start + heading * distance
    near = _candidates(world, np.minimum(start, end) - radius, np.maximum(start, end) + radius, skip)
    if not near:
        return None
    cache: dict[int, Any] = {}

    def touching(travelled: float) -> bool:
        probe = SphereProxy(start + heading * travelled, radius)
        return any(collide(-1, j, probe, _proxy(world, j, cache)) for j in near)

    if touching(0.0):
        return 0.0
    step = max(radius * 0.5, distance / 2048.0)
    clear, travelled = 0.0, step
    while clear < distance:
        travelled = min(travelled, distance)
        if touching(travelled):
            low, high = clear, travelled
            for _ in range(_BISECTIONS):
                middle = (low + high) / 2.0
                if touching(middle):
                    high = middle
                else:
                    low = middle
            return high
        clear, travelled = travelled, travelled + step
    return None


def overlapping(world: PhysicsWorld, shape: model.Shape, position: Any, orientation: Any,
                skip: Collection[int] = ()) -> list[int]:
    """Indices of the solid bodies ``shape`` overlaps when placed at ``position`` and ``orientation``."""
    quaternion = np.asarray(orientation, dtype='d')
    centre = np.asarray(position, dtype='d')
    lo, hi = world_aabb(shape, centre, quaternion)
    probe = make_proxy(shape, centre, quaternion)
    cache: dict[int, Any] = {}
    return [j for j in _candidates(world, lo, hi, skip)
            if collide(-1, j, probe, _proxy(world, j, cache))]
