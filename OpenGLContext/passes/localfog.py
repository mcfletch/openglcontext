"""Which LocalFog fogs a draw: X3D's LocalFog scope -- no GL

An enabled `LocalFog` fogs the siblings in its parent group and their
descendants, in place of the scene's bound `Fog`; where LocalFogs nest, the
deepest group's fogs what is inside it (ISO/IEC 19775-1, 24.4.2).
:func:`local_fogs` gathers a frame's enabled ones with the groups they fog
under, and :func:`fog_for` answers the one a draw's path is in.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Optional, TypeAlias

__all__ = ['fog_for', 'local_fogs']

#: (the fog's ancestors from the root, the fog's path), deepest group first.
Scoped: TypeAlias = 'tuple[tuple[tuple[Any, ...], Any], ...]'


def local_fogs(paths: Iterable[Sequence[Any]]) -> Scoped:
    """The enabled LocalFogs among `paths`, deepest group first"""
    found = [(tuple(path[:-1]), path) for path in paths if getattr(path[-1], 'enabled', True)]
    found.sort(key=lambda item: -len(item[0]))
    return tuple(found)


def fog_for(scoped: Scoped, path: Sequence[Any]) -> Optional[Any]:
    """The path of the LocalFog fogging the node at the end of `path`, or None"""
    for ancestors, fog in scoped:
        if len(path) > len(ancestors) and all(
                path[index] is ancestor for index, ancestor in enumerate(ancestors)):
            return fog
    return None
