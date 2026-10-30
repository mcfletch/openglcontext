"""Questions asked of an omi_physics world on the calling thread: rays, sweeps and overlaps.

These work over a :class:`~omi_physics.world.PhysicsWorld` that the calling
thread may read: the live world of an inline service, or the render thread's
:class:`~OpenGLContext.physics.replica.Replica`. Candidates are found by the
world's bounding boxes, so a query costs the bodies near it and not the scene.
"""
from __future__ import annotations

import math
from collections.abc import Collection
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

import numpy as np
from omi_physics import model
from omi_physics.body import SphereProxy, make_proxy, pose_key, world_aabb
from omi_physics.collide import collide

from OpenGLContext.physics.omi_adapter import omi_shape
from OpenGLContext.physics.types import Hit

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.physics.proxy import Proxy

__all__ = ['Hit', 'overlapping', 'proxy_bounds', 'raycast', 'raycast_many', 'sweep_sphere']

_IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])
#: How many halvings find where a swept sphere first touches.
_BISECTIONS = 14


def _candidates(world: PhysicsWorld, lo: np.ndarray, hi: np.ndarray,
                skip: Collection[int], triggers: bool = False) -> list[int]:
    """Indices of the solid bodies, or with ``triggers`` the trigger volumes, whose box meets ``lo`` to ``hi``, minus ``skip``."""
    shapes = world.trigger_shape if triggers else world.collider_shape
    near = ((shapes >= 0) & np.all(world.aabb_max >= lo, axis=1)
            & np.all(world.aabb_min <= hi, axis=1))
    return [j for j in np.flatnonzero(near).tolist()
            if j not in skip and (triggers or not world.is_sensor(j))
            and world.handle_of(world.ref(j)) is not None]


#: Each world's proxies for the bodies queries have met: a proxy for a mesh
#: costs a grid over its triangles, and a body that has not moved keeps its own.
_PROXIES: WeakKeyDictionary[Any, dict[tuple[int, bool], tuple[model.Shape, tuple[float, ...], Any]]] = (
    WeakKeyDictionary())


def _proxy(world: PhysicsWorld, index: int, triggers: bool = False) -> Any:
    """The proxy of body ``index`` where it is now, made again only where its shape or pose differ."""
    held = _PROXIES.setdefault(world, {})
    shape = world.shapes[world.trigger_shape[index] if triggers else world.collider_shape[index]]
    pose = pose_key(world.position[index], world.orientation[index])
    found = held.get((index, triggers))
    if found is None or found[0] is not shape or found[1] != pose:
        found = held[(index, triggers)] = (
            shape, pose, make_proxy(shape, world.position[index], world.orientation[index]))
    return found[2]


def sweep_sphere(world: PhysicsWorld, origin: Any, direction: Any, distance: float,
                 radius: float, skip: Collection[int] = ()) -> float | None:
    """How far a sphere of ``radius`` can travel from ``origin`` along ``direction``.

    Returns the distance at which it first touches a solid body, 0 where it
    starts in one, or None where it travels ``distance`` clear. The sphere is
    stepped by half its radius, so a wall thinner than that can be passed. A
    fixed body is tested only at the distances where the sphere's box meets
    the body's (:func:`_reach_along`); a body that moves is tested at every one.
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
    reaches = [_reach_along(world, j, start, heading, radius) for j in near]

    def touching(travelled: float) -> bool:
        probe = SphereProxy(start + heading * travelled, radius)
        return any(collide(-1, j, probe, _proxy(world, j)) for j, (first, last) in
                   zip(near, reaches, strict=True) if first <= travelled <= last)

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


#: How far, in metres, past the box of a fixed body a swept sphere's box is still tested against it.
_REACH_SLACK = 1e-6


def _reach_along(world: PhysicsWorld, index: int, start: np.ndarray, heading: np.ndarray,
                 radius: float) -> tuple[float, float]:
    """The distances along ``heading`` from ``start`` between which a sphere of ``radius`` there
    has a box that meets body ``index``'s, grown by :data:`_REACH_SLACK`.

    Everywhere, ``(-inf, inf)``, for a body that moves: its box was fitted
    before its last move. A fixed body lies inside its box, so a sphere whose
    box misses it touches nothing of it.
    """
    if world.motion_type[index] != 0:
        return -math.inf, math.inf
    first, last = -math.inf, math.inf
    low, high = world.aabb_min[index].tolist(), world.aabb_max[index].tolist()
    for axis in range(3):
        bottom = low[axis] - radius - _REACH_SLACK
        top = high[axis] + radius + _REACH_SLACK
        origin, rate = float(start[axis]), float(heading[axis])
        if rate == 0.0:
            if not bottom <= origin <= top:
                return math.inf, -math.inf
            continue
        enter, leave = (bottom - origin) / rate, (top - origin) / rate
        if enter > leave:
            enter, leave = leave, enter
        first, last = max(first, enter), min(last, leave)
    slack = _REACH_SLACK * (1.0 + abs(first) + abs(last)) if math.isfinite(first + last) else 0.0
    return first - slack, last + slack


def overlapping(world: PhysicsWorld, proxy: Proxy, position: Any, orientation: Any,
                skip: Collection[int] = (), triggers: bool = False) -> list[int]:
    """Indices of the solid bodies, or with ``triggers`` the trigger volumes, ``proxy`` overlaps.

    ``proxy`` is placed at ``position`` and ``orientation`` (a quaternion).
    """
    shape = omi_shape(proxy)
    quaternion = np.asarray(orientation, dtype='d')
    centre = np.asarray(position, dtype='d')
    lo, hi = world_aabb(shape, centre, quaternion)
    probe = make_proxy(shape, centre, quaternion)
    return [j for j in _candidates(world, lo, hi, skip, triggers)
            if collide(-1, j, probe, _proxy(world, j, triggers))]


def raycast(world: PhysicsWorld, origin: Any, direction: Any, distance: float,
            skip: Collection[int]) -> Any:
    """omi's first hit of a ray, or None, passing through the bodies in slots ``skip``."""
    from omi_physics.collisionquery import WorldQuery  # noqa: PLC0415 only a service that casts needs it

    return WorldQuery(world).raycast(origin, direction, float(distance), skip)


def raycast_many(world: PhysicsWorld, origins: Any, directions: Any, distance: float,
                 skip: Collection[int]) -> list[Any]:
    """omi's first hit of each ray, or None for each that meets nothing."""
    from omi_physics.raycast import raycast_many as cast  # noqa: PLC0415 only a service that casts needs it

    return list(cast(world, origins, directions, float(distance), skip))


def proxy_bounds(proxy: Proxy, position: Any, orientation: Any) -> tuple[np.ndarray, np.ndarray]:
    """The world box of ``proxy`` at ``position`` turned by the quaternion ``orientation``."""
    low, high = world_aabb(omi_shape(proxy), np.asarray(position, dtype='d'), orientation)
    return np.asarray(low), np.asarray(high)
