"""Which lights light a draw: X3D's and VRML97's light scope -- no GL

A light whose `global` field is false lights only the descendants of its
parent grouping node; a global light lights everything. X3D defaults a
`DirectionalLight` to scoped and point and spot lights to global, as VRML97
does; the engine's own `DirectionalLight`, made in code, is global.

The render pass binds lights to slots in the order of their paths. For each
draw it sets a `lightsOff` mask, one bit per slot, and :func:`scope_mask`
gives the bits for the scoped lights the draw is outside. :class:`ScopeMasks`
keeps each path's bits while the same lights are scoped.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, TypeAlias

__all__ = ['ScopeMasks', 'is_global', 'scope_mask', 'scoped_lights']

#: (slot, the light's ancestors from the root) for each scoped light.
Scoped: TypeAlias = 'tuple[tuple[int, tuple[Any, ...]], ...]'


def is_global(light: Any) -> bool:
    """Whether `light` lights the whole scene: its `global` field, true where it has none"""
    return bool(getattr(light, 'global', True))


def scoped_lights(light_paths: Iterable[Sequence[Any]]) -> Scoped:
    """The scoped lights among those bound, by slot, with the ancestors they light under

    `light_paths` are the bound lights' paths in slot order.
    """
    return tuple((slot, tuple(path[:-1])) for slot, path in enumerate(light_paths)
                 if not is_global(path[-1]))


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
