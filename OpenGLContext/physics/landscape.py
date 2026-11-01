"""A landscape as bodies in the physics world: the ground, the trunks and the rocks near a focus.

A landscape of kilometres is too large to hold as a triangle mesh, and the
renderer already answers its height at any point. So the world holds the ground
as a body that answers a height at each point
(:meth:`Physics.add_ground <OpenGLContext.physics.service.Physics.add_ground>`)
over the same
:class:`~OpenGLContext.scenegraph.vegetation.grid.Ground` the terrain node draws
(:class:`Landscape`), the trunks standing on it as static cylinders in a few
radius classes, and the rocks as bodies made when a focus comes within reach
and dropped when it leaves (:class:`NearbyColliders`). A walker, a thrown ball
and a vehicle then meet the same ground and the same trunks.

A ground whose ``sample`` is expensive, such as a height field with rock
displaced over it, is read through :class:`SampledGround`, which keeps tiles of
its own samples: a character asks for dozens of heights in a step, and the
ground answers each tile once.
"""
from __future__ import annotations

import collections
import concurrent.futures
import functools
import math
import threading
from collections.abc import Callable, Hashable, Sequence
from typing import Any

import logging

import numpy as np

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.sources import Changes

log = logging.getLogger(__name__)

__all__ = ['DOME_SINK', 'Landscape', 'NearbyColliders', 'SampledGround', 'TRUNK_HEIGHT',
           'TRUNK_SINK', 'dome_proxy', 'ground_figures']

#: How tall a trunk's cylinder is, in metres: higher than a walker, a thrown body
#: or a vehicle reaches.
TRUNK_HEIGHT = 24.0

#: How far below the ground a trunk's cylinder starts, in metres, so that no gap
#: shows on a slope.
TRUNK_SINK = 1.0

#: The difference in radius, in metres, between one trunk shape and the next.
#: A trunk takes the radius class above its own, so the world is never softer
#: than the trunk it stands for.
RADIUS_STEP = 0.05

#: The thinnest trunk, in metres.
MIN_RADIUS = 0.05

#: A radius within this share of a class step above a class belongs to it, so that
#: 0.3 held as a 32-bit float is not made the class above for its rounding.
_SLACK = 1e-5

#: How far a dome reaches below its position, in metres.
DOME_SINK = 0.3

#: How finely a dome's measurements are told apart, in metres. Domes within this
#: of each other share a shape.
DOME_STEP = 0.01

#: Divisions of a dome's profile and of its girth.
_DOME_RINGS = 9
_DOME_SIDES = 16

#: The share of the range of a sampled ground by which its heights are widened.
SAMPLED_MARGIN = 0.2

#: Metres of ground a tile of :class:`SampledGround` holds along each side.
TILE_METRES = 32.0

#: The most points whose answer :class:`SampledGround` keeps for the next ask.
MEMO_POINTS = 256

#: Tiles :class:`SampledGround` keeps.
TILES_KEPT = 64

#: How fine :class:`SampledGround` samples a ground that names no spacing, in metres.
SAMPLE_SPACING = 0.5

_Extent = tuple[tuple[float, float], tuple[float, float]]


def ground_figures(ground: Any, extent: Any = None) -> tuple[_Extent | None, tuple[float, float], float]:
    """``(extent, (low, high), feature)`` for ``ground``: where it is, how high, and how finely it changes.

    ``extent`` is ``((x_min, z_min), (x_max, z_max))``. Given None it is the
    ground's own: a ground with an ``extent`` in metres is the square of that
    side about the origin, and any other has none.

    ``low`` and ``high`` are exact for a ground that carries a ``grid``,
    ``relief`` and ``base`` (a
    :class:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField`, with the
    height of any ``rock`` stood on it added) and sampled over the extent for any
    other. They are widened by a metre, and by a fifth of the range for a sampled
    ground, whose samples miss the peaks between them.

    ``feature`` is the horizontal distance over which the height changes: the
    ground's ``spacing`` where it has one, else one cell of its grid, else a metre.
    """
    if extent is None:
        edge = getattr(ground, 'extent', None)
        if isinstance(edge, (int, float)) and math.isfinite(edge):
            half = float(edge) / 2.0
            extent = ((-half, -half), (half, half))
    grid = getattr(ground, 'grid', None)
    relief = getattr(ground, 'relief', None)
    if grid is not None and relief is not None:
        heights = np.asarray(grid, dtype='d')
        base = float(getattr(ground, 'base', 0.0))
        low = base + float(heights.min()) * float(relief)
        high = base + float(heights.max()) * float(relief)
        rock = getattr(ground, 'rock', None)
        if rock is not None:
            high += max(float(getattr(rock, 'height', 0.0)), 0.0)
    else:
        (x0, z0), (x1, z1) = extent if extent is not None else ((-500.0, -500.0), (500.0, 500.0))
        xs, zs = np.meshgrid(np.linspace(x0, x1, 65), np.linspace(z0, z1, 65))
        sampled = np.asarray(ground.sample(xs, zs), dtype='d')
        low, high = float(sampled.min()), float(sampled.max())
        # Samples miss the peaks between them.
        margin = max(high - low, 1.0) * SAMPLED_MARGIN
        low, high = low - margin, high + margin
    feature = getattr(ground, 'spacing', None)
    if feature is None:
        cells = np.shape(grid)[0] - 1 if grid is not None else 0
        edge = getattr(ground, 'extent', None)
        feature = float(edge) / cells if cells > 0 and isinstance(edge, (int, float)) else 1.0
    return extent, (low - 1.0, high + 1.0), float(feature)


class SampledGround:
    """A ground answered from tiles of its own samples.

    ``ground.sample(x, z)`` is called once for each tile of ``tile`` metres, on a
    grid ``spacing`` metres apart, and a point is answered by interpolating its
    tile. The tiles last ``kept`` at a time and are made by whichever thread
    asks first. ``sample`` takes arrays of any shape, or numbers.

    A tile of ground with rock on it takes a tenth of a second to make, which a
    walker must not wait for. :meth:`prefetch` makes the tiles about a point on a
    thread of its own, so they are there when the walker reaches them.
    """

    def __init__(self, ground: Any, spacing: float = SAMPLE_SPACING, tile: float = TILE_METRES,
                 kept: int = TILES_KEPT) -> None:
        if not (spacing > 0.0 and tile >= spacing and kept >= 1):
            raise ValueError('tiles of %r metres sampled every %r metres, %r kept'
                             % (tile, spacing, kept))
        self.ground = ground
        self._cells = max(int(round(tile / spacing)), 1)
        self.tile = float(tile)
        self.spacing = self.tile / self._cells
        self._kept = int(kept)
        self._tiles: collections.OrderedDict[tuple[int, int], np.ndarray] = collections.OrderedDict()
        self._lock = threading.Lock()
        self._done = threading.Condition(self._lock)
        self._pending: set[tuple[int, int]] = set()
        self._pool: concurrent.futures.ThreadPoolExecutor | None = None
        self._last: tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None

    def __getattr__(self, name: str) -> Any:
        if name in ('ground', '_tiles', '_lock', '_last', '_done', '_pending', '_pool'):
            raise AttributeError(name)
        return getattr(self.ground, name)

    @property
    def tile_count(self) -> int:
        """How many tiles are kept."""
        with self._lock:
            return len(self._tiles)

    def prefetch(self, x: float, z: float, around: int = 1) -> None:
        """Make the tiles within ``around`` tiles of ``(x, z)`` on a thread of their own, nearest first."""
        centre = (float(x) / self.tile, float(z) / self.tile)
        here = (math.floor(centre[0]), math.floor(centre[1]))
        keys = sorted(((here[0] + i, here[1] + j)
                       for i in range(-around, around + 1) for j in range(-around, around + 1)),
                      key=lambda key: math.hypot(key[0] + 0.5 - centre[0], key[1] + 0.5 - centre[1]))
        with self._lock:
            wanted = [key for key in keys if key not in self._tiles and key not in self._pending]
            self._pending.update(wanted)
            if wanted and self._pool is None:
                self._pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix='ground-tiles')
            pool = self._pool
        for key in wanted:
            assert pool is not None
            pool.submit(self._make, key)

    def _make(self, key: tuple[int, int]) -> None:
        """Make one tile ahead of its asking."""
        try:
            self._tile_of(key)
        except Exception:
            log.exception('the ground tile %r could not be made', key)
        finally:
            with self._done:
                self._pending.discard(key)
                self._done.notify_all()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until the tiles asked for ahead are made; False if ``timeout`` seconds were not enough."""
        with self._done:
            return self._done.wait_for(lambda: not self._pending, timeout)

    def close(self) -> None:
        """Stop making tiles ahead. The tiles made stay, and an asked-for tile is still made."""
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def _tile_of(self, key: tuple[int, int]) -> np.ndarray:
        """The samples of tile ``key``, ``(cells + 1, cells + 1)`` with rows along z."""
        with self._lock:
            found = self._tiles.get(key)
            if found is not None:
                self._tiles.move_to_end(key)
                return found
        along = np.arange(self._cells + 1, dtype='d') * self.spacing
        xs, zs = np.meshgrid(key[0] * self.tile + along, key[1] * self.tile + along)
        made = np.asarray(self.ground.sample(xs, zs), dtype='d')
        with self._lock:
            kept = self._tiles.setdefault(key, made)
            self._tiles.move_to_end(key)
            while len(self._tiles) > self._kept:
                self._tiles.popitem(last=False)
        return kept

    def sample(self, x: Any, z: Any) -> np.ndarray:
        """The height at each ``(x, z)``, in the shape of ``x`` and ``z`` together."""
        return self._answer(x, z)[0]

    def normal(self, x: Any, z: Any) -> np.ndarray:
        """The unit normal of the ground at each ``(x, z)``, as ``(..., 3)`` with +y up.

        The slope of the cell the point is in, so it is the normal of the
        surface :meth:`sample` interpolates.
        """
        slope_x, slope_z = self._answer(x, z)[1:]
        out = np.stack((-slope_x, np.ones_like(slope_x), -slope_z), axis=-1)
        normals: np.ndarray = out / np.linalg.norm(out, axis=-1, keepdims=True)
        return normals

    def _answer(self, x: Any, z: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Heights and slopes at the points, as the last few points asked were answered.

        A height and a normal are asked at the same points one after the other,
        so the last small set of points is kept with its answer.
        """
        x = np.asarray(x, dtype='d')
        z = np.asarray(z, dtype='d')
        kept = self._last
        if kept is not None and np.array_equal(x, kept[0]) and np.array_equal(z, kept[1]):
            return kept[2]
        answer = self._read(x, z, True)
        if x.size <= MEMO_POINTS and z.size <= MEMO_POINTS:
            self._last = (x.copy(), z.copy(), answer)
        return answer

    def _read(self, x: Any, z: Any, slopes: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The height at each point, and with ``slopes`` the rise per metre along x and along z."""
        x, z = np.broadcast_arrays(np.asarray(x, dtype='d'), np.asarray(z, dtype='d'))
        shape = x.shape
        xs, zs = x.reshape(-1), z.reshape(-1)
        out = np.empty(len(xs))
        rise_x = np.empty(len(xs)) if slopes else out
        rise_z = np.empty(len(xs)) if slopes else out
        column = np.floor(xs / self.tile).astype(np.int64)
        row = np.floor(zs / self.tile).astype(np.int64)
        if len(xs) and column.min() == column.max() and row.min() == row.max():
            groups: list[tuple[int, int, Any]] = [(int(column[0]), int(row[0]), slice(None))]
        else:
            groups = [(tile_x, tile_z, (column == tile_x) & (row == tile_z))
                      for tile_x, tile_z in np.unique(np.stack((column, row), axis=1),
                                                      axis=0).tolist()]
        for tile_x, tile_z, here in groups:
            grid = self._tile_of((tile_x, tile_z))
            u = np.clip((xs[here] - tile_x * self.tile) / self.spacing, 0.0, self._cells)
            v = np.clip((zs[here] - tile_z * self.tile) / self.spacing, 0.0, self._cells)
            i = np.minimum(np.floor(u).astype(np.int64), self._cells - 1)
            j = np.minimum(np.floor(v).astype(np.int64), self._cells - 1)
            fu, fv = u - i, v - j
            low, high = grid[j, i], grid[j + 1, i]
            low_next, high_next = grid[j, i + 1], grid[j + 1, i + 1]
            out[here] = (low * (1.0 - fu) + low_next * fu) * (1.0 - fv) \
                + (high * (1.0 - fu) + high_next * fu) * fv
            if slopes:
                rise_x[here] = ((low_next - low) * (1.0 - fv) + (high_next - high) * fv) / self.spacing
                rise_z[here] = ((high - low) * (1.0 - fu) + (high_next - low_next) * fu) / self.spacing
        return out.reshape(shape), rise_x.reshape(shape), rise_z.reshape(shape)


class Landscape:
    """The ground and the trunks of a landscape, as bodies in ``physics``.

    ``ground`` is anything that answers ``sample(x, z)`` for arrays: the surface
    the terrain node draws. ``trunks`` is an ``(n, 3)`` array of positions and
    ``radii`` an ``(n,)`` array of radii in metres; each trunk is a cylinder
    :data:`TRUNK_HEIGHT` metres tall standing on the ground under its ``x`` and
    ``z``, whatever its ``y``, and trunks whose radii fall in the same
    :data:`RADIUS_STEP` share a shape. No ``radii`` makes posts of the thinnest
    radius.

    ``extent`` is the ground's ``((x_min, z_min), (x_max, z_max))``, taken from
    the ground where it is left out. ``cache`` reads the ground through
    :class:`SampledGround`; the default is to do so for any ground that is not a
    height field. The other options are those of
    :meth:`~OpenGLContext.physics.service.Physics.add_static`.
    """

    def __init__(self, physics: Any, ground: Any, trunks: Any = None, radii: Any = None, *,
                 extent: Any = None, cache: bool | None = None,
                 trunk_height: float = TRUNK_HEIGHT, trunk_sink: float = TRUNK_SINK,
                 radius_step: float = RADIUS_STEP, **material: Any) -> None:
        from OpenGLContext.scenegraph.terrain.heightfield import HeightField  # noqa: PLC0415 imports the scenegraph

        self.physics = physics
        self.ground = ground
        wrap = cache if cache is not None else not isinstance(ground, HeightField)
        spacing = float(getattr(ground, 'spacing', SAMPLE_SPACING))
        #: What the world's ground samples: ``ground``, or tiles of it.
        self.surface: Any = SampledGround(ground, spacing) if wrap else ground
        bounds, heights, feature = ground_figures(ground, extent)
        #: The ground's body.
        self.body = physics.add_ground(self.surface, extent=bounds, height_range=heights,
                                       feature=feature, **material)
        #: The sets of trunks that share a shape, one for each radius class.
        self.trunks: list[Any] = []
        self._removed = False
        self._following: Any = None
        if trunks is not None and len(trunks):
            self._stand_trunks(np.asarray(trunks, dtype='d').reshape(-1, 3), radii,
                               float(trunk_height), float(trunk_sink), float(radius_step),
                               material)

    @property
    def trunk_count(self) -> int:
        """How many trunks there are."""
        return sum(trunk.count for trunk in self.trunks)

    def _stand_trunks(self, positions: np.ndarray, radii: Any, height: float, sink: float,
                      step: float, material: dict[str, Any]) -> None:
        """Make a cylinder of each trunk, on the ground, one shape for each radius class."""
        if radii is None:
            wide = np.zeros(len(positions))
        else:
            wide = np.asarray(radii, dtype='d').reshape(-1)
            if len(wide) != len(positions):
                raise ValueError('%d trunks and %d radii' % (len(positions), len(wide)))
        # Read from the ground itself: the trunks stand where the ground is drawn.
        under = np.asarray(self.ground.sample(positions[:, 0], positions[:, 2]), dtype='d')
        classes = np.maximum(np.ceil(wide / step - _SLACK) * step, MIN_RADIUS)
        for radius in np.unique(np.round(classes, 9)):
            these = np.isclose(classes, radius)
            centres = np.stack((positions[these, 0], under[these] - sink + height / 2.0,
                                positions[these, 2]), axis=1)
            self.trunks.append(self.physics.add_static_instances(
                Proxy.cylinder(height, float(radius)), centres, **material))

    def follow(self, focus: Callable[[], Any]) -> Any:
        """Make the tiles of a ground read through :class:`SampledGround` about ``focus()`` ahead of its asking.

        ``focus`` is called once a frame and answers where the walker, or whatever else
        moves over the ground, is. Returns the source, whose ``remove()`` stops it, or
        None for a ground that is not read through tiles.
        """
        if not isinstance(self.surface, SampledGround):
            return None
        self._following = self.physics.add_collider_source(_TilesAhead(self.surface), focus=focus)
        return self._following

    def remove(self) -> None:
        """Take the ground and the trunks out of the world. Removing twice is harmless."""
        if self._removed:
            return
        self._removed = True
        if self._following is not None:
            self._following.remove()
        if isinstance(self.surface, SampledGround):
            self.surface.close()
        self.body.remove()
        for trunk in self.trunks:
            trunk.remove()
        self.trunks = []


class _TilesAhead:
    """A collider source that makes no body: it asks a ground for the tiles about the focus."""

    def __init__(self, ground: SampledGround) -> None:
        self.ground = ground
        self._tile: tuple[int, int] | None = None

    def update(self, focus: Sequence[float]) -> Changes:
        """Have the tiles about ``focus`` made, once the focus is in a tile it has not been in."""
        tile = (math.floor(float(focus[0]) / self.ground.tile),
                math.floor(float(focus[2]) / self.ground.tile))
        if tile != self._tile:
            self._tile = tile
            self.ground.prefetch(float(focus[0]), float(focus[2]))
        return Changes()


@functools.lru_cache(maxsize=512)
def _dome(radius: int, rim: int, top: int) -> Proxy:
    """The proxy of a dome measured in whole :data:`DOME_STEP`s."""
    reach, edge, apex = radius * DOME_STEP, rim * DOME_STEP, max(top, rim) * DOME_STEP
    angles = np.linspace(0.0, math.pi / 2.0, _DOME_RINGS)
    around = np.linspace(0.0, 2.0 * math.pi, _DOME_SIDES, endpoint=False)
    points = [(0.0, apex, 0.0)]
    for angle in angles[1:]:
        width = reach * math.sin(angle)
        height = edge + (apex - edge) * math.cos(angle)
        points.extend((width * math.cos(a), height, width * math.sin(a)) for a in around)
    points.extend((reach * math.cos(a), -DOME_SINK, reach * math.sin(a)) for a in around)
    return Proxy.convex(np.asarray(points, dtype='d'))


def dome_proxy(radius: float, rim: float, top: float) -> Proxy:
    """A solid dome over a circle of ``radius`` metres, ``rim`` high at its edge and ``top`` at its middle.

    The surface is half an ellipse from the rim to the top, with a vertical side
    down to :data:`DOME_SINK` metres below the position the body is put at.
    Measurements within :data:`DOME_STEP` of each other give the same proxy.
    """
    def whole(metres: float) -> int:
        return max(int(round(float(metres) / DOME_STEP)), 1)

    return _dome(whole(radius), whole(rim), whole(top))


@functools.lru_cache(maxsize=64)
def _column(height: float, radius: float) -> Proxy:
    return Proxy.cylinder(height, radius)


class NearbyColliders:
    """Bodies for the rocks and posts a field answers for, as a focus nears them.

    A :class:`~OpenGLContext.physics.sources.ColliderSource`. ``answer(x, z,
    reach)`` returns ``(positions, radii)``, an ``(n, 3)`` and an ``(n,)``
    array, for the things within ``reach`` metres of ``(x, z)``: each becomes a
    cylinder :attr:`height` metres tall standing on its position, which a walker
    is pushed out of at any height. It may return ``(positions, radii, rims,
    tops)`` instead, with two more ``(n,)`` arrays, for domes
    (:func:`dome_proxy`) that a walker climbs where the surface rises no more than
    its step height. A field such as
    :meth:`~OpenGLContext.scenegraph.rockfield.RockField.mounds_near` is one.

    Things within ``reach`` metres of the focus (a square, as the field takes it)
    are made. Those already made stay until they are past ``reach * keep``, so a
    focus pacing the edge of one does not make it and drop it again. The field is
    asked again once the focus has moved ``refresh`` metres, and may be asked
    from the thread the world is stepped on.
    """

    def __init__(self, answer: Callable[[float, float, float], Sequence[Any]], *,
                 reach: float = 24.0, keep: float = 1.25, refresh: float = 2.0,
                 height: float = TRUNK_HEIGHT, sink: float = TRUNK_SINK,
                 radius_step: float = RADIUS_STEP) -> None:
        if not (reach > 0.0 and keep >= 1.0 and refresh >= 0.0):
            raise ValueError('reach %r, keep %r, refresh %r' % (reach, keep, refresh))
        self.answer = answer
        self.reach = float(reach)
        self.keep = float(keep)
        self.refresh = float(refresh)
        self.height = float(height)
        self.sink = float(sink)
        self.radius_step = float(radius_step)
        self._held: set[Hashable] = set()
        self._asked_at: tuple[float, float] | None = None

    def update(self, focus: Sequence[float]) -> Changes:
        """The things to make and to drop now that the focus is at ``focus``."""
        x, z = float(focus[0]), float(focus[2])
        if self._asked_at is not None and math.hypot(
                x - self._asked_at[0], z - self._asked_at[1]) < self.refresh:
            return Changes()
        self._asked_at = (x, z)
        found = self.answer(x, z, self.reach * self.keep)
        positions = np.asarray(found[0], dtype='d').reshape(-1, 3)
        radii = np.asarray(found[1], dtype='d').reshape(-1)
        domes = len(found) >= 4
        rims = np.asarray(found[2], dtype='d').reshape(-1) if domes else None
        tops = np.asarray(found[3], dtype='d').reshape(-1) if domes else None
        near = (np.abs(positions[:, 0] - x) <= self.reach) & (np.abs(positions[:, 2] - z) <= self.reach)
        present: set[Hashable] = set()
        added: list[tuple[Hashable, Proxy, Sequence[float], Sequence[float] | None]] = []
        for row, (px, py, pz) in enumerate(positions.tolist()):
            if domes:
                assert rims is not None and tops is not None
                key: Hashable = (px, py, pz, float(radii[row]), float(rims[row]), float(tops[row]))
            else:
                key = (px, py, pz, float(radii[row]))
            present.add(key)
            if key in self._held or not near[row]:
                continue
            if domes:
                assert rims is not None and tops is not None
                added.append((key, dome_proxy(radii[row], rims[row], tops[row]), (px, py, pz), None))
            else:
                wide = max(math.ceil(float(radii[row]) / self.radius_step - _SLACK) * self.radius_step,
                           MIN_RADIUS)
                added.append((key, _column(self.height, round(wide, 9)),
                              (px, py - self.sink + self.height / 2.0, pz), None))
        gone = [key for key in self._held if key not in present]
        self._held.difference_update(gone)
        self._held.update(key for key, *_ in added)
        return Changes(add=added, remove=gone)
