"""X3D's AcousticProperties: the surfaces sound meets, and what they do to it -- no GL

A shape whose appearance has an enabled ``AcousticProperties`` is an acoustic
surface. Its `absorption`, `diffuse` and `specular` are read as shares of the
sound energy striking it: absorbed, reflected in many directions, reflected as
from a mirror. What is left passes through it (:func:`transmission`).

:class:`Acoustics` holds a frame's surfaces in world coordinates and answers
two questions:

- :meth:`Acoustics.occlusion` - the gain on a sound reaching the listener
  along the straight path from the source: the square root of the product of
  each crossed surface's transmission, since the shares are of energy and a
  gain scales amplitude; :class:`~OpenGLContext.audio.x3dgraph.SoundGraph`
  scales each Sound and SpatialSound by it.
- :meth:`Acoustics.reverb` - for a listener inside the box round every
  surface, the reverb of that room: its decay is Sabine's reverberation time,
  ``0.161 V / A`` seconds for the box's volume ``V`` in cubic metres and
  ``A`` the sum of each surface's area times the share it does not reflect;
  its level the square root of the surfaces' reflection averaged by area. The render pass lays
  any zone's reverb over it (:func:`OpenGLContext.audio.areas.apply_zones`).

`refraction` is not read: the engine hears a sound along one straight path,
which a surface does not bend. The surfaces are one room, the box round all
of them, and reflections are heard only as the reverb, not as separate echoes.

Reference:
    https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/shape.html#AcousticProperties
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

import numpy as np
from numpy.typing import NDArray

from OpenGLContext.scenegraph import meshdata

if TYPE_CHECKING:
    from OpenGLContext.passes.zonelayers import Reverb

__all__ = ['Acoustics', 'MAX_DECAY', 'SABINE', 'Surface', 'properties_of', 'reflection',
           'transmission']

#: A point, as three numbers or more (a homogeneous position's fourth is ignored).
Point = Sequence[float] | NDArray[Any]

#: Sabine's constant, seconds per metre: 24 ln 10 over the speed of sound.
SABINE = 0.161

#: The longest reverb a room is given, in seconds, for one that absorbs
#: nearly nothing.
MAX_DECAY = 10.0

#: How near either end of the path a crossing may be and still not count, as
#: a share of its length: a source or listener on a surface is not behind it.
_ENDS = 1e-6


def properties_of(shape: Any) -> Any:
    """`shape`'s enabled AcousticProperties, or None"""
    appearance = getattr(shape, 'appearance', None)
    found = getattr(appearance, 'acousticProperties', None) if appearance else None
    if found and bool(found.enabled):
        return found
    return None


def reflection(properties: Any) -> float:
    """The share of the sound striking a surface that it reflects, diffuse and specular"""
    return min(1.0, max(0.0, float(properties.diffuse) + float(properties.specular)))


def transmission(properties: Any) -> float:
    """The share of the sound striking a surface that passes through it"""
    taken = float(properties.absorption) + float(properties.diffuse) + float(properties.specular)
    return min(1.0, max(0.0, 1.0 - taken))


class Surface(NamedTuple):
    """One shape's triangles in world coordinates, and what it does to sound"""

    #: (n, 3, 3) corners, double precision.
    triangles: NDArray[np.float64]
    transmission: float
    reflection: float
    #: The triangles' area, square metres.
    area: float


def _world_triangles(arrays: Any, matrix: Any) -> NDArray[np.float64]:
    """The triangles of composed `arrays`, carried by the row-vector `matrix`"""
    positions = np.asarray(arrays.attributes['POSITION'], dtype=np.float64)
    count = len(positions)
    corners = (np.arange((count // 3) * 3) if arrays.indices is None
               else np.asarray(arrays.indices, dtype=np.int64).ravel())
    placed = np.asarray(matrix, dtype=np.float64)
    moved = positions @ placed[:3, :3] + placed[3, :3]
    found: NDArray[np.float64] = moved[corners[:len(corners) // 3 * 3]].reshape(-1, 3, 3)
    return found


class Acoustics:
    """A frame's acoustic surfaces, held from one frame to the next

    :meth:`update` is given the shapes with their world matrices. A shape's
    triangles are read and carried into the world again only when its matrix
    or its bounding volume is another object than last time: both are kept in
    the scenegraph's caches until something they are worked out from is set.
    """

    def __init__(self) -> None:
        self.surfaces: list[Surface] = []
        self._placed: dict[Any, tuple[Any, Any, NDArray[np.float64], float]] = {}
        self._triangles: NDArray[np.float64] = np.zeros((0, 3, 3))
        #: Each surface's transmission, and the surface each triangle is of.
        self._passes: NDArray[np.float64] = np.zeros(0)
        self._owners: NDArray[np.int64] = np.zeros(0, dtype=np.int64)
        self._low: Optional[NDArray[np.float64]] = None
        self._high: Optional[NDArray[np.float64]] = None

    def __bool__(self) -> bool:
        return bool(self.surfaces)

    def update(self, placed: Sequence[tuple[Any, Any]]) -> None:
        """Take the frame's shapes, each ``(shape, world matrix)``; those without
        enabled acoustic properties are passed over"""
        surfaces: list[Surface] = []
        kept: dict[Any, tuple[Any, Any, NDArray[np.float64], float]] = {}
        for shape, matrix in placed:
            properties = properties_of(shape)
            if properties is None:
                continue
            if not shape.geometry:
                continue
            volume = shape.boundingVolume(None)
            held = self._placed.get(shape)
            if held is None or held[0] is not matrix or held[1] is not volume:
                arrays = meshdata.geometry_arrays(shape.geometry)
                if arrays is None:
                    continue
                triangles = _world_triangles(arrays, matrix)
                sides = np.cross(triangles[:, 1] - triangles[:, 0],
                                 triangles[:, 2] - triangles[:, 0])
                held = (matrix, volume, triangles, float(np.linalg.norm(sides, axis=1).sum()) / 2)
            kept[shape] = held
            surfaces.append(Surface(held[2], transmission(properties), reflection(properties),
                                    held[3]))
        self._placed = kept
        self.surfaces = surfaces
        if surfaces:
            self._triangles = np.concatenate([found.triangles for found in surfaces])
            self._passes = np.array([found.transmission for found in surfaces])
            self._owners = np.concatenate([np.full(len(found.triangles), number)
                                           for number, found in enumerate(surfaces)])
            corners = self._triangles.reshape(-1, 3)
            self._low, self._high = corners.min(axis=0), corners.max(axis=0)
        else:
            self._triangles = np.zeros((0, 3, 3))
            self._passes = np.zeros(0)
            self._owners = np.zeros(0, dtype=np.int64)
            self._low = self._high = None

    def occlusion(self, source: Point, listener: Point) -> float:
        """The gain on a sound at `source` reaching `listener` through the surfaces"""
        if not len(self._triangles):
            return 1.0
        start = np.asarray(source, dtype=np.float64)[:3]
        way = np.asarray(listener, dtype=np.float64)[:3] - start
        hit, distance = self._crossed(start, way)
        if not hit.any():
            return 1.0
        # A path through an edge or a corner meets each triangle sharing it at
        # one distance: that is one crossing of the surface.
        owners, distance = self._owners[hit], distance[hit]
        order = np.lexsort((distance, owners))
        owners, distance = owners[order], distance[order]
        new = np.ones(len(owners), dtype=bool)
        new[1:] = (owners[1:] != owners[:-1]) | (np.diff(distance) > _ENDS)
        return math.sqrt(float(np.prod(self._passes[owners[new]])))

    def _crossed(self, start: NDArray[np.float64],
                 way: NDArray[np.float64]) -> tuple[NDArray[np.bool_], NDArray[np.float64]]:
        """Which triangles the segment from `start` along `way` crosses, and at what
        share of its length (Moller-Trumbore)"""
        first = self._triangles[:, 0]
        edge1 = self._triangles[:, 1] - first
        edge2 = self._triangles[:, 2] - first
        across = np.cross(way, edge2)
        determinant = np.einsum('ij,ij->i', edge1, across)
        usable = np.abs(determinant) > 1e-12
        inverse = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=usable)
        offset = start - first
        u = np.einsum('ij,ij->i', offset, across) * inverse
        turned = np.cross(offset, edge1)
        v = (turned @ way) * inverse
        t = np.einsum('ij,ij->i', edge2, turned) * inverse
        found: NDArray[np.bool_] = (usable & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0)
                                    & (t > _ENDS) & (t < 1.0 - _ENDS))
        return found, t

    def reverb(self, listener: Point) -> Optional[Reverb]:
        """The room's reverb heard at `listener`; None outside the box round the
        surfaces, or where they enclose no volume"""
        from OpenGLContext.passes.zonelayers import Reverb  # noqa: PLC0415 the passes package imports GL
        if self._low is None or self._high is None:
            return None
        point = np.asarray(listener, dtype=np.float64)[:3]
        if np.any(point < self._low) or np.any(point > self._high):
            return None
        volume = float(np.prod(self._high - self._low))
        area = sum(found.area for found in self.surfaces)
        if volume <= 0.0 or area <= 0.0:
            return None
        absorbing = sum(found.area * (1.0 - found.reflection) for found in self.surfaces)
        decay = SABINE * volume / absorbing if absorbing > 0.0 else math.inf
        level = math.sqrt(sum(found.area * found.reflection for found in self.surfaces) / area)
        return Reverb(level=level, decay=min(decay, MAX_DECAY))
