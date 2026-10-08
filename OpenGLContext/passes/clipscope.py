"""Which ClipPlanes clip a draw, and their planes in its frame -- no GL

An enabled X3D `ClipPlane` (ISO/IEC 19775-1, 11.4.1) clips its siblings in
their parent group and everything under them: a point is kept where its
`plane` (a, b, c, d) gives a*x + b*y + c*z + d of zero or more, in the
ClipPlane's own coordinate system. Planes nest: every enabled ClipPlane
whose group leads to a draw clips it, the nearest group's first, up to
:data:`MAX_PLANES`.

:class:`ClipPlanes` holds a frame's enabled ClipPlanes with their planes in
world coordinates; :meth:`ClipPlanes.object_planes` gives a draw's planes in
the drawn object's own frame, which is where the vertex shaders and
`glClipPlane` take them, so one set of planes serves every view, mirror and
shadow map the object is drawn into.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Optional

import numpy as np

__all__ = ['MAX_PLANES', 'ClipPlanes', 'clipped_by_pass', 'object_plane', 'world_plane']

log = logging.getLogger(__name__)

#: The planes that clip one draw: the clip distances every GL implementation has.
MAX_PLANES = 8


def world_plane(plane: Any, matrix: Optional[Any]) -> np.ndarray:
    """`plane` in a frame placed by the row-vector `matrix`, in world coordinates"""
    found = np.asarray(plane, dtype=np.float64).reshape(4)
    if matrix is None:
        return found
    world: np.ndarray = np.linalg.inv(np.asarray(matrix, dtype=np.float64)) @ found
    return world


def object_plane(world: np.ndarray, matrix: Any) -> np.ndarray:
    """The world plane `world` in the frame of an object placed by `matrix`, of unit normal"""
    found = np.asarray(matrix, dtype=np.float64) @ world
    length = float(np.linalg.norm(found[:3]))
    unit: np.ndarray = found / length if length > 0 else found
    return unit


def clipped_by_pass(node: Any) -> bool:
    """Whether the pass clips `node`'s draw: a shape drawn with the pass's own programs

    A shape whose appearance brings its own program, or whose geometry draws
    with a program of its own (a terrain or vegetation layer), writes no clip
    distances, so it is drawn unclipped.
    """
    geometry = getattr(node, 'geometry', None)
    if not geometry or hasattr(geometry, 'ensure_gl'):
        return False
    return not getattr(getattr(node, 'appearance', None), 'bringsProgram', False)


def _enabled(path: Sequence[Any]) -> bool:
    return bool(getattr(path[-1], 'enabled', True))


def _same_paths(first: Sequence[Sequence[Any]], second: Sequence[Sequence[Any]]) -> bool:
    return len(first) == len(second) and all(
        len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=True))
        for a, b in zip(first, second, strict=True))


class ClipPlanes:
    """A frame's enabled ClipPlanes, and the ones that reach each path drawn

    Which planes reach a path is worked out the first time it is asked and
    kept with the path while the same ClipPlanes are enabled in the same
    places; the planes themselves are read again each frame (:meth:`following`).
    """

    #: How many paths' answers are kept before the record starts afresh.
    KEPT_LIMIT = 50000

    def __init__(self, paths: Iterable[Sequence[Any]] = ()) -> None:
        self.paths: tuple[Any, ...] = tuple(path for path in paths if _enabled(path))
        self.ancestors = tuple(tuple(path[:-1]) for path in self.paths)
        self.world = np.zeros((len(self.paths), 4))
        self._reaching: dict[int, tuple[Any, tuple[int, ...]]] = {}
        self._read()

    def __bool__(self) -> bool:
        return bool(self.paths)

    def _read(self) -> None:
        for index, path in enumerate(self.paths):
            self.world[index] = world_plane(path[-1].plane, path.transformMatrix())

    def following(self, paths: Iterable[Sequence[Any]]) -> ClipPlanes:
        """The ClipPlanes of `paths` this frame: these, re-read, where they are the same"""
        enabled = [path for path in paths if _enabled(path)]
        if _same_paths(enabled, self.paths):
            self._read()
            return self
        return ClipPlanes(enabled)

    def reaching(self, path: Sequence[Any]) -> tuple[int, ...]:
        """The planes that clip the node at the end of `path`, nearest group first"""
        if not self.paths:
            return ()
        found = self._reaching.get(id(path))
        if found is not None and found[0] is path:
            return found[1]
        reach = [(len(ancestors), index) for index, ancestors in enumerate(self.ancestors)
                 if len(path) > len(ancestors)
                 and all(path[step] is node for step, node in enumerate(ancestors))]
        reach.sort(key=lambda item: -item[0])
        if len(reach) > MAX_PLANES:
            log.warning('%d ClipPlanes reach %s; the nearest %d clip it',
                        len(reach), path[-1], MAX_PLANES)
        value = tuple(index for _depth, index in reach[:MAX_PLANES])
        if len(self._reaching) >= self.KEPT_LIMIT:
            self._reaching.clear()
        self._reaching[id(path)] = (path, value)  # noqa: OGC131 the entry holds the path, so its id is not reused while kept
        return value

    def object_planes(self, path: Sequence[Any], matrix: Any) -> np.ndarray:
        """The planes clipping `path`'s node, in the frame `matrix` places it in; (n, 4)"""
        chosen = self.reaching(path)
        found = np.zeros((len(chosen), 4), dtype=np.float32)
        for row, index in enumerate(chosen):
            found[row] = object_plane(self.world[index], matrix)
        return found

    def apart(self, path: Sequence[Any]) -> Optional[object]:
        """What keeps a draw out of an instanced group: a token of its own where planes clip it

        An instanced draw has one set of planes in one object's frame, so a
        clipped object is drawn by itself; an unclipped one answers None.
        """
        return object() if self.reaching(path) else None
