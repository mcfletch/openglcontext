"""Which lights light a draw: X3D's and VRML97's light scope -- no GL

A light whose `global` field is false lights only the descendants of its
parent grouping node; a global light lights everything. X3D defaults a
`DirectionalLight` to scoped and point and spot lights to global, as VRML97
does; the engine's own `DirectionalLight`, made in code, is global.

The render pass binds lights to slots in the order of their paths. For each
draw it sets a `lightsOff` mask, one bit per slot, and :func:`scope_mask`
gives the bits for the scoped lights the draw is outside. :class:`ScopeMasks`
keeps each path's bits while the same lights are scoped.

A point or spot light's `radius` is a cut-off per fragment in the shader
paths. The fixed-function pipeline has none, so the compatibility profile
switches a light off for each draw whose bounds its radius does not reach:
:func:`reaching_lights` gives each bounded light's sphere in world
coordinates, and :func:`reach_mask` the bits for a draw's world box.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any, TypeAlias

import numpy as np

__all__ = ['ScopeMasks', 'is_global', 'reach_mask', 'reaching_lights', 'scope_mask',
           'scoped_lights']

#: (slot, the light's ancestors from the root) for each scoped light.
Scoped: TypeAlias = 'tuple[tuple[int, tuple[Any, ...]], ...]'
#: (slot, centre, radius) in world coordinates for each light with a radius.
Reaching: TypeAlias = 'tuple[tuple[int, np.ndarray, float], ...]'


def is_global(light: Any) -> bool:
    """Whether `light` lights the whole scene: its `global` field, true where it has none"""
    return bool(getattr(light, 'global', True))


def scoped_lights(light_paths: Iterable[Sequence[Any]], first: int = 0) -> Scoped:
    """The scoped lights among those bound, by slot, with the ancestors they light under

    `light_paths` are the bound lights' paths in slot order, the first at
    slot `first`: texture projectors take the slots from
    :data:`~OpenGLContext.passes.projectorpass.PROJECTOR_SCOPE_BIT`.
    """
    return tuple((slot, tuple(path[:-1])) for slot, path in enumerate(light_paths, first)
                 if not is_global(path[-1]))


def reaching_lights(bound: Iterable[tuple[int, Any, Any]]) -> Reaching:
    """The bound lights with a finite `radius`, each as a sphere in world coordinates

    `bound` is (slot, light, the light's world matrix) for each bound light.
    The radius is in the light's own coordinates, so it is scaled by the
    matrix's largest axis, as the shader paths scale it.
    """
    found = []
    for slot, light, matrix in bound:
        radius = float(getattr(light, 'radius', math.inf))
        location = getattr(light, 'location', None)
        if location is None or not math.isfinite(radius):
            continue
        placed = np.asarray(matrix, dtype=np.float64)
        centre = np.append(np.asarray(location, dtype=np.float64), 1.0) @ placed
        scale = float(np.linalg.norm(placed[:3, :3], axis=1).max())
        found.append((slot, centre[:3], radius * scale))
    return tuple(found)


def reach_mask(reaching: Reaching, low: Any, high: Any) -> int:
    """One bit per light of `reaching` whose sphere misses the box `low` to `high`"""
    mask = 0
    if not reaching:
        return mask
    low = np.asarray(low, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    for slot, centre, radius in reaching:
        nearest = np.clip(centre, low, high)
        if float(np.dot(nearest - centre, nearest - centre)) > radius * radius:
            mask |= 1 << slot
    return mask


def scope_mask(scoped: Scoped, path: Sequence[Any]) -> int:
    """One bit per scoped light whose ancestors do not lead to `path`'s node"""
    mask = 0
    for slot, ancestors in scoped:
        if len(path) <= len(ancestors) or any(
                path[index] is not ancestor for index, ancestor in enumerate(ancestors)):
            mask |= 1 << slot
    return mask


class ScopeMasks:
    """The scope bits of each path drawn under one set of scoped lights

    A path's bits are worked out the first time it is asked about; the path
    is held with them, so its identity is not reused for another while they
    are kept. :meth:`following` answers this object while the scoped lights
    stay equal, and a fresh one when they change.
    """

    #: How many paths' bits are kept before the record starts afresh.
    KEPT_LIMIT = 50000

    def __init__(self, scoped: Scoped = ()) -> None:
        self.scoped = scoped
        self._masks: dict[int, tuple[Any, int]] = {}

    def __bool__(self) -> bool:
        return bool(self.scoped)

    def following(self, scoped: Scoped) -> ScopeMasks:
        """The masks for `scoped`: these, where they are the same lights"""
        if scoped == self.scoped:
            return self
        return ScopeMasks(scoped)

    def mask(self, path: Sequence[Any]) -> int:
        """`path`'s bits (:func:`scope_mask`)"""
        if not self.scoped:
            return 0
        found = self._masks.get(id(path))
        if found is not None and found[0] is path:
            return found[1]
        value = scope_mask(self.scoped, path)
        if len(self._masks) >= self.KEPT_LIMIT:
            self._masks.clear()
        self._masks[id(path)] = (path, value)  # noqa: OGC131 the entry holds the path, so its id is not reused while kept
        return value
