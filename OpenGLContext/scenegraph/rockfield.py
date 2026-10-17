"""Rocks scattered over any ground, made as the camera nears them.

:class:`RockScatter` is a tile generator (see
:mod:`OpenGLContext.loaders.tiles3d.generated`): the world is divided into square
cells, and each cell's rocks are made, seated on the ground and merged into one mesh when
the camera comes within reach. :class:`RockField` is the scene node that streams them.

The rocks are :func:`~OpenGLContext.scenegraph.natural.stone`\\ s. A cell's rocks depend only
on the seed and the cell, so a cell made twice is the same, and neighbouring cells meet
without a seam. A big rock has smaller ones lying at its foot, as fallen rock does, and each
rock is sunk a little into the ground.
"""
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from OpenGLContext.loaders.tiles3d.boundingvolume import BoxBV
from OpenGLContext.scenegraph import natural
from OpenGLContext.scenegraph import surfaces as sf
from OpenGLContext.scenegraph.generatedtiles import GeneratedTiles
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.vegetation.grid import Ground

__all__ = ['RockField', 'RockScatter', 'cells_near']

#: Rocks bigger than this (radius, metres) have smaller rocks lying about them.
CLUSTER_FROM = 0.3
#: Rocks smaller than this (radius, metres) are walked over and have no collider, and a
#: rock's collider is this share of its radius: its footprint is rounder than its widest
#: reach.
COLLIDE_FROM = 0.25
FOOTPRINT = 0.9
#: Rocks of each size are divided this finely: below the first radius 1 division, below the
#: second 2, above that 3. See :func:`~OpenGLContext.scenegraph.natural.stone`.
DETAIL = (0.22, 0.45)
#: How many cells' colliders a field keeps.
CELLS_KEPT = 64
#: The ground is read at this many points along each side of a cell, for the cell's bounds.
BOUND_SAMPLES = 5


@dataclass(frozen=True)
class RockTile:
    """What the tile runtime takes of a generated tile: the node to draw."""

    group: Group


def cells_near(point: np.ndarray, radius: float, cell: float) -> list[tuple[int, int]]:
    """The square cells ``cell`` metres wide, as ``(i, j)``, that reach within ``radius`` metres
    of the ground point under ``point`` (``x``, ``y``, ``z``), nearest first."""
    x, z = float(point[0]), float(point[2])
    first_i, last_i = math.floor((x - radius) / cell), math.floor((x + radius) / cell)
    first_j, last_j = math.floor((z - radius) / cell), math.floor((z + radius) / cell)
    reach = radius + cell * math.sqrt(0.5)
    near = [(math.hypot((i + 0.5) * cell - x, (j + 0.5) * cell - z), i, j)
            for i in range(first_i, last_i + 1) for j in range(first_j, last_j + 1)]
    return [(i, j) for distance, i, j in sorted(near) if distance <= reach]


class RockScatter:
    """A tile generator that scatters rocks over ``ground``.

    ``ground`` answers ``sample(x, z)`` with a height. ``material`` is what the rocks wear.
    ``mask(x, z)``, if given, answers how likely a rock is at each point, from 0 to 1, and
    scales the largest rock that grows there. ``density`` is rocks per square metre where
    the mask is 1, ``sizes`` the radius in metres of the smallest and the largest, ``cell``
    the width of a tile in metres, and ``seed`` what the scatter is drawn from.
    """

    def __init__(self, ground: Ground, material: Any,
                 mask: Optional[Callable[[Any, Any], Any]] = None, density: float = 0.01,
                 sizes: tuple[float, float] = (0.12, 0.9), cell: float = 64.0,
                 seed: int = 0) -> None:
        if not 0.0 < sizes[0] <= sizes[1]:
            raise ValueError('rock sizes %r are not a smallest and a largest radius' % (sizes,))
        if cell <= 0.0 or density < 0.0:
            raise ValueError('a rock cell is %s m wide and %s rocks a square metre'
                             % (cell, density))
        self.ground, self.material, self.mask = ground, material, mask
        self.density, self.sizes, self.cell, self.seed = float(density), sizes, float(cell), seed

    # -- the generator protocol --
    def keys_near(self, point: np.ndarray, radius: float) -> list[tuple[int, int]]:
        """The cells within ``radius`` metres of ``point``, nearest first."""
        return cells_near(point, radius, self.cell)

    def origin(self, key: tuple[int, int]) -> tuple[float, float, float]:
        """The corner of a cell: its meshes are built around it so their vertices stay small."""
        return (key[0] * self.cell, 0.0, key[1] * self.cell)

    def bounds(self, key: tuple[int, int]) -> BoxBV:
        """The box that holds the rocks of a cell."""
        x0, _, z0 = self.origin(key)
        axis = np.linspace(0.0, self.cell, BOUND_SAMPLES)
        gx, gz = np.meshgrid(x0 + axis, z0 + axis)
        heights = np.asarray(self.ground.sample(gx, gz), dtype=float)
        low = float(heights.min()) - 0.5 * self.sizes[1]
        high = float(heights.max()) + 1.5 * self.sizes[1]
        reach = self.cell / 2.0 + self.sizes[1] * 2.0
        return BoxBV((x0 + self.cell / 2.0, (low + high) / 2.0, z0 + self.cell / 2.0),
                     [(reach, 0.0, 0.0), (0.0, (high - low) / 2.0, 0.0), (0.0, 0.0, reach)])

    def _rng(self, key: tuple[int, int]) -> np.random.Generator:
        """The generator a cell draws from: the same for the same seed and cell."""
        return np.random.default_rng([int(self.seed) & 0xFFFFFFFF, key[0] & 0xFFFFFFFF,
                                      key[1] & 0xFFFFFFFF])

    def _placements(self, key: tuple[int, int], rng: np.random.Generator
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Where the rocks of a cell lie and how big they are, as ``x``, ``z`` and radius.

        Draws from ``rng`` in a fixed order, so that what :meth:`generate` and
        :meth:`colliders` take from one cell agree about every rock.
        """
        x0, _, z0 = self.origin(key)
        count = rng.poisson(self.density * self.cell * self.cell)
        x = x0 + rng.uniform(0.0, self.cell, count)
        z = z0 + rng.uniform(0.0, self.cell, count)
        likely = np.ones(count) if self.mask is None else np.clip(
            np.asarray(self.mask(x, z), dtype=float), 0.0, 1.0)
        lo, hi = self.sizes
        chosen = rng.random(count) < likely
        radii = lo + (hi * (0.4 + 0.6 * likely) - lo) * rng.random(count) ** 2
        stones = [(x[i], z[i], max(lo, radii[i])) for i in np.flatnonzero(chosen)]
        for px, pz, radius in list(stones):
            if radius > CLUSTER_FROM:
                for _ in range(int(rng.integers(1, 4))):
                    turn, reach = rng.uniform(0.0, 2.0 * math.pi), radius * rng.uniform(1.0, 1.7)
                    stones.append((px + reach * math.cos(turn), pz + reach * math.sin(turn),
                                   max(lo, radius * rng.uniform(0.25, 0.55))))
        if not stones:
            return np.zeros(0), np.zeros(0), np.zeros(0)
        columns = zip(*stones, strict=True)
        ex, ez, er = (np.array(column, dtype=float) for column in columns)
        return ex, ez, er

    def generate(self, key: tuple[int, int]) -> tuple[RockTile, int]:
        """The rocks of a cell as a node to draw, and its size in bytes. Runs on a worker."""
        rng = self._rng(key)
        x0, _, z0 = self.origin(key)
        ex, ez, er = self._placements(key, rng)
        if not len(er):
            return RockTile(Group()), 0
        ground = np.asarray(self.ground.sample(ex, ez), dtype=float)
        parts = [sf.placed(self._rock(rng, float(er[j])),
                           (float(ex[j] - x0), float(ground[j] + 0.2 * er[j]), float(ez[j] - z0)))
                 for j in range(len(er))]
        mesh = sf.merge(parts)
        node = sf.shape(mesh, self.material)
        node.children[0].castShadow = True
        size = int(sum(array.nbytes for array in mesh))
        return RockTile(Group(children=[node])), size

    def colliders(self, key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """What stops a walker among the rocks of a cell: ``(positions, radii)``.

        Positions are ``(N, 3)`` world points on the ground under each rock and radii the
        rock's footprint, as the cylinders a walker is pushed out of. Rocks smaller than
        :data:`COLLIDE_FROM` are underfoot, not in the way, and are left out. The cell is
        worked out from the seed alone, with no meshes built, so it can be asked of cells
        nothing has drawn.
        """
        ex, ez, er = self._placements(key, self._rng(key))
        keep = er >= COLLIDE_FROM
        if not keep.any():
            return np.zeros((0, 3), 'f'), np.zeros(0, 'f')
        ground = np.asarray(self.ground.sample(ex[keep], ez[keep]), dtype=float)
        positions = np.stack([ex[keep], ground, ez[keep]], axis=-1).astype('f')
        return positions, (er[keep] * FOOTPRINT).astype('f')

    @staticmethod
    def _rock(rng: np.random.Generator, radius: float) -> sf.Geometry:
        """One rock about the origin, flattened a little and turned."""
        divisions = 1 if radius < DETAIL[0] else 2 if radius < DETAIL[1] else 3
        shape = (radius, radius * rng.uniform(0.55, 0.8), radius * rng.uniform(0.8, 1.3))
        return sf.placed(natural.stone(rng, shape, divisions), (0.0, 0.0, 0.0),
                         (0.0, 1.0, 0.0, rng.uniform(0.0, 2.0 * math.pi)))


class RockField(GeneratedTiles):
    """Rocks over ``ground`` around the camera: a :class:`~OpenGLContext.scenegraph.generatedtiles.GeneratedTiles`
    node fed by a :class:`RockScatter`.

    ``ground``, ``material``, ``mask``, ``density``, ``sizes``, ``cell`` and ``seed`` are the
    scatter's. ``reach`` is how far from the camera, in metres, a cell is made. Call
    :meth:`update_for_camera` once a frame with the GL context current.
    """

    def __init__(self, ground: Ground, material: Any, reach: float = 120.0,
                 mask: Optional[Callable[[Any, Any], Any]] = None, density: float = 0.01,
                 sizes: tuple[float, float] = (0.12, 0.9), cell: float = 64.0, seed: int = 0,
                 **named: Any) -> None:
        self.scatter = RockScatter(ground, material, mask, density, sizes, cell, seed)
        self._held: OrderedDict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = OrderedDict()
        self._lock = threading.Lock()
        super().__init__(self.scatter, reach, **named)

    def colliders_near(self, x: float, z: float, reach: float = 3.0
                       ) -> tuple[np.ndarray, np.ndarray]:
        """The colliders of the rocks within a square ``reach`` metres either side of ``(x, z)``.

        ``(positions, radii)`` as :meth:`RockScatter.colliders` answers for each cell the
        square touches. A walker asks this every step, so a cell's answer is kept (the
        last :data:`CELLS_KEPT` cells), and one is worked out the first time it is asked
        for whether or not it has been drawn. Safe to call from any thread.
        """
        cell = self.scatter.cell
        positions, radii = [], []
        for i in range(math.floor((x - reach) / cell), math.floor((x + reach) / cell) + 1):
            for j in range(math.floor((z - reach) / cell), math.floor((z + reach) / cell) + 1):
                here, size = self._cell((i, j))
                if len(size):
                    positions.append(here)
                    radii.append(size)
        if not positions:
            return np.zeros((0, 3), 'f'), np.zeros(0, 'f')
        return np.concatenate(positions), np.concatenate(radii)

    def _cell(self, key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            held = self._held.get(key)
            if held is not None:
                self._held.move_to_end(key)
                return held
        made = self.scatter.colliders(key)
        with self._lock:
            self._held[key] = made
            while len(self._held) > CELLS_KEPT:
                self._held.popitem(last=False)
        return made
