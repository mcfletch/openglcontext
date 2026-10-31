"""A proxy's mass properties and bounds: volume, centroid, inertia, the box it fills -- no GL

Every shape is a solid of uniform density. A ``convex`` or ``trimesh`` proxy
is measured as the box its points span, and a ``capsule`` as the cylinder of
its height and radius, so a body weighs and turns on every engine as it does
on the omi engine. A ``compound`` shares its mass among its parts by volume;
its inertia is the sum of theirs about the compound's origin.

:func:`inertia_diagonal` is the diagonal X3D's ``RigidBody`` takes as its
default inertia: the products of inertia a lopsided compound has are left
out. The formulas are those of omi_physics' ``massprops`` (MIT, Mike C.
Fletcher); ``tests/unit/test_physics_massprops.py`` compares the two while
omi_physics is installed.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from OpenGLContext.physics.proxy import Proxy

__all__ = ['bounds', 'centroid', 'inertia_diagonal', 'inertia_tensor', 'rotation_matrix', 'volume']

#: Gauss-Legendre nodes and weights on [-1, 1], exact for the degree-4
#: polynomials a narrowing cylinder's integrals are.
_NODES, _WEIGHTS = np.polynomial.legendre.leggauss(3)
_LEVEL = (0.0, 0.0, 0.0, 1.0)


def rotation_matrix(turn: Sequence[float]) -> np.ndarray:
    """The 3x3 rotation of a unit quaternion ``(x, y, z, w)``"""
    x, y, z, w = (float(v) for v in turn)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def volume(proxy: Proxy) -> float:
    """The proxy's volume in cubic metres, by the rules above"""
    params, kind = proxy.params, proxy.kind
    if kind == 'sphere':
        return 4.0 / 3.0 * np.pi * params['radius'] ** 3
    if kind == 'box':
        return float(np.prod(params['size']))
    if kind == 'capsule':
        return float(np.pi * params['radius'] ** 2 * params['height'])
    if kind == 'cylinder':
        bottom, top = params['radius'], params['radius_top']
        return float(np.pi * params['height'] * (bottom * bottom + bottom * top + top * top) / 3.0)
    if kind == 'compound':
        return float(sum(volume(part) for part, _position, _turn in params['parts']))
    extent = _extent(proxy)
    return float(np.prod(extent[1] - extent[0])) if extent is not None else 0.0


def centroid(proxy: Proxy) -> np.ndarray:
    """Where the proxy's mass is, in its own frame"""
    kind = proxy.kind
    if kind == 'cylinder':
        return np.array([0.0, _cylinder_moments(proxy)[2], 0.0])
    if kind == 'compound':
        parts = proxy.params['parts']
        if not parts:
            return np.zeros(3)
        found: np.ndarray = np.sum([share * _part_centroid(part)
                                    for share, part in zip(_shares(parts), parts, strict=True)],
                                   axis=0)
        return found
    if kind in ('convex', 'trimesh'):
        extent = _extent(proxy)
        return np.zeros(3) if extent is None else 0.5 * (extent[0] + extent[1])
    return np.zeros(3)


def inertia_tensor(proxy: Proxy, mass: float) -> np.ndarray:
    """The 3x3 inertia tensor of ``mass`` kilograms spread through the proxy

    About the proxy's centroid, except a ``compound``, which is about its own
    origin: the body's origin, where its parts are placed from.
    """
    if proxy.kind != 'compound':
        return np.diag(_principal(proxy, mass))
    parts = proxy.params['parts']
    total = np.zeros((3, 3))
    for share, part in zip(_shares(parts), parts, strict=True):
        part_mass = mass * share
        turn = rotation_matrix(part[2])
        total += turn @ _about_centroid(part[0], part_mass) @ turn.T
        total += _shifted(_part_centroid(part), part_mass)
    return total


def inertia_diagonal(proxy: Proxy | None, mass: float) -> np.ndarray:
    """The diagonal of the proxy's inertia tensor (:func:`inertia_tensor`); zeros for None"""
    if proxy is None:
        return np.zeros(3)
    return np.diag(inertia_tensor(proxy, mass)).copy()


def bounds(proxy: Proxy, position: Sequence[float] = (0.0, 0.0, 0.0),
           orientation: Sequence[float] = _LEVEL) -> tuple[np.ndarray, np.ndarray]:
    """The axis-aligned box ``(low, high)`` the proxy fills at a pose

    Raises ValueError for a ``heightfield``, which has no box.
    """
    centre = np.asarray(position, dtype='d')
    turn = rotation_matrix(orientation)
    params, kind = proxy.params, proxy.kind
    half: np.ndarray
    if kind == 'box':
        half = np.abs(turn) @ (0.5 * np.asarray(params['size'], dtype='d'))
    elif kind == 'sphere':
        half = np.full(3, float(params['radius']))
    elif kind == 'capsule':
        radius = float(params['radius'])
        half = np.abs(turn[:, 1]) * 0.5 * float(params['height']) + radius
    elif kind == 'cylinder':
        axis = turn[:, 1]
        across = np.sqrt(np.clip(1.0 - axis * axis, 0.0, None))
        ends = [(-0.5 * float(params['height']), float(params['radius'])),
                (0.5 * float(params['height']), float(params['radius_top']))]
        low = np.min([axis * along - across * radius for along, radius in ends], axis=0)
        high = np.max([axis * along + across * radius for along, radius in ends], axis=0)
        return centre + low, centre + high
    elif kind in ('convex', 'trimesh'):
        points = np.asarray(params['points'], dtype='d').reshape(-1, 3)
        if not len(points):
            return centre.copy(), centre.copy()
        placed = points @ turn.T + centre
        return placed.min(axis=0), placed.max(axis=0)
    elif kind == 'compound':
        boxes = [bounds(part, centre + turn @ np.asarray(place, dtype='d'),
                        _multiply(orientation, part_turn))
                 for part, place, part_turn in params['parts']]
        if not boxes:
            return centre.copy(), centre.copy()
        return (np.min([low for low, _ in boxes], axis=0),
                np.max([high for _, high in boxes], axis=0))
    else:
        raise ValueError('a %s proxy has no bounding box' % (kind,))
    return centre - half, centre + half


def _multiply(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float, float]:
    """The quaternion turning by ``b`` then by ``a``"""
    ax, ay, az, aw = (float(v) for v in a)
    bx, by, bz, bw = (float(v) for v in b)
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _shifted(offset: np.ndarray, mass: float) -> np.ndarray:
    """What carrying ``mass`` at ``offset`` adds to an inertia tensor (parallel axes)"""
    return mass * (np.dot(offset, offset) * np.eye(3) - np.outer(offset, offset))


def _about_centroid(proxy: Proxy, mass: float) -> np.ndarray:
    """A proxy's inertia tensor about its centroid, in its own frame"""
    if proxy.kind != 'compound':
        return np.diag(_principal(proxy, mass))
    return inertia_tensor(proxy, mass) - _shifted(centroid(proxy), mass)


def _principal(proxy: Proxy, mass: float) -> np.ndarray:
    """A proxy's inertia about its centroid, along its own axes"""
    params, kind = proxy.params, proxy.kind
    if kind == 'sphere':
        return np.full(3, 0.4 * mass * params['radius'] ** 2)
    if kind == 'box':
        return _box(np.asarray(params['size'], dtype='d'), mass)
    if kind == 'capsule':
        radius, height = params['radius'], params['height']
        across = mass * (3 * radius * radius + height * height) / 12.0
        return np.array([across, 0.5 * mass * radius * radius, across])
    if kind == 'cylinder':
        axial, across, offset = _cylinder_moments(proxy)
        across -= offset * offset
        return mass * np.array([across, axial, across])
    extent = _extent(proxy)
    if extent is None:
        return np.zeros(3)
    return _box(extent[1] - extent[0], mass)


def _box(size: np.ndarray, mass: float) -> np.ndarray:
    """A solid box's inertia about its centre"""
    x, y, z = size
    return mass / 12.0 * np.array([y * y + z * z, x * x + z * z, x * x + y * y])


def _cylinder_moments(proxy: Proxy) -> tuple[float, float, float]:
    """Per kilogram: the axial moment, the moment across the origin, and the centroid height

    The radius narrows linearly from ``radius`` at ``-height/2`` to
    ``radius_top`` at ``+height/2``; each slice is a disc.
    """
    params = proxy.params
    height, bottom, top = params['height'], params['radius'], params['radius_top']
    half = 0.5 * height
    heights = _NODES * half
    radii = bottom + (top - bottom) * (heights + half) / max(height, 1e-12)
    area = radii * radii
    weights = _WEIGHTS * half
    amount = float(np.dot(weights, area))
    if amount <= 0.0:
        return 0.0, 0.0, 0.0
    axial = float(np.dot(weights, area * area / 2.0)) / amount
    across = float(np.dot(weights, area * (area / 4.0 + heights * heights))) / amount
    offset = float(np.dot(weights, area * heights)) / amount
    return axial, across, offset


def _extent(proxy: Proxy) -> tuple[np.ndarray, np.ndarray] | None:
    """The box a point-cloud proxy's points span, or None for one with none"""
    points = proxy.params.get('points')
    if points is None or not len(points):
        return None
    points = np.asarray(points, dtype='d').reshape(-1, 3)
    return points.min(axis=0), points.max(axis=0)


def _shares(parts: Sequence[tuple[Proxy, Any, Any]]) -> np.ndarray:
    """Each part's fraction of a compound's mass: by volume, or equal where none has any"""
    volumes = np.array([volume(part) for part, _position, _turn in parts], dtype='d')
    total = float(volumes.sum())
    if total <= 0.0 and len(parts):
        return np.full(len(parts), 1.0 / len(parts))
    return volumes / total


def _part_centroid(part: tuple[Proxy, Any, Any]) -> np.ndarray:
    """Where a compound part's mass is, in the compound's frame"""
    proxy, position, turn = part
    return np.asarray(position, dtype='d') + rotation_matrix(turn) @ centroid(proxy)
