"""The grain in a landscape: relief too fine to be part of its shape.

A world's height function says where the hills are. What it does not say is what
a hillside is made of -- the hummocks, the ruts and the swells a metre or two
across that a player standing on it sees and a map of the terrain never carries.
Sampling the height function more finely does not produce them, because they are
not in it; :class:`Relief` is.

Relief is a band of noise per feature size, and a surface carries the bands it is
sampled finely enough to show. A tile meshed every sixty metres carries none of
them, and one meshed every half metre carries them all, so the grain arrives as a
3D Tiles tree refines rather than aliasing into a coarse tile as speckle.

The displacement is scaled to fit inside the tile's own geometric error, which
is the distance the streamer is already willing for the drawn surface to stand
from the real one. So one level never moves the ground further than the level
above it was allowed to be wrong by.

What is drawn is what is collided against. The height field a world carries is
the one surface every reader uses -- the car, the camera, the seat of a
scattered plant -- so the grain goes into it, and the tiles are meshed from the
same function; the coarser levels are that surface with its finer bands left
off. A band the field's own grid could not hold would be relief a player sees
and walks through, and :meth:`Relief.no_finer_than` removes those before
anything draws them.

``where`` says how much grain each place gets: ground that was worked, such as
a road, has none.

Its bake-time use is :mod:`OpenGLContext_editor.bake.layers`, which meshes each
tile of ground from the height function with its own relief added, and
``OpenGLContext_editor.world.procedural.ProceduralWorld``, which puts the same
grain in the landscape beside the tileset.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from OpenGLContext.noise import fbm, smoothstep

HeightFn = Callable[[Any, Any], Any]
#: ``where(x, z) -> weight``: how much of the grain a place gets, 0 to 1.
Weight = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class Relief:
    """Bands of noise from ``coarsest`` down to ``finest``, in metres.

    ``roughness`` is how steep the grain is -- metres of rise per metre of
    feature -- and sets each band's amplitude from its own size, so the relief
    reads as one surface rather than as a fine ripple laid over a coarse one.

    ``samples_per_feature`` is how many vertices a feature needs before it is
    drawn at all. Below it a band would land between samples and come out as
    speckle, which is the thing a coarse tile must not carry.

    ``seed`` chooses which grain; two reliefs differing only in it share no
    feature.

    ``where(x, z) -> weight`` says how much of the grain a place gets, from 0
    to 1. Not every surface has grain in it: a road is built by levelling the
    ground it runs on, and a hummock through the carriageway is a hummock a
    grader took out. Left out, the grain is everywhere.
    """

    #: The largest feature the grain has, in metres. Small, because this is
    #: the grain *in* a hillside and not another hillside laid over it: a band
    #: is as tall as ``roughness`` times its own width, so a coarse band is a
    #: dune. A landscape's shape is the height function's job.
    coarsest: float = 16.0
    #: The smallest, in metres. Nothing below it is ever added, whatever the
    #: spacing, since past a point a mesh is not how ground is textured.
    finest: float = 0.75
    #: Metres of rise per metre of feature. A thirtieth is a swell a car
    #: crosses without noticing it is there; grain a car is stopped by is not
    #: grain, it is terrain.
    roughness: float = 0.03
    #: How many vertices across a feature before it is drawn rather than
    #: aliased. Four is the fewest that resolves a feature at all, and what it
    #: resolves it to is four flat facets with a crease at every sample -- a
    #: surface a wheel catches on. Eight is a swell.
    samples_per_feature: float = 8.0
    #: Which grain of this description.
    seed: int = 0
    #: How much of the grain each place gets, from 0 to 1, or None for all of
    #: it everywhere.
    where: Weight | None = None

    def __post_init__(self) -> None:
        if self.finest <= 0.0:
            raise ValueError(
                "relief's finest feature must be larger than 0 m, not %r"
                % (self.finest,))
        if self.coarsest < self.finest:
            raise ValueError(
                "relief runs from its coarsest feature (%r) down to its finest "
                "(%r)" % (self.coarsest, self.finest))
        if self.samples_per_feature < 2.0:
            raise ValueError(
                "relief needs at least 2 samples per feature, not %r"
                % (self.samples_per_feature,))

    def wavelengths(self) -> tuple[float, ...]:
        """Every feature size this relief is made of, coarsest first."""
        sizes, size = [], float(self.coarsest)
        while size >= self.finest:
            sizes.append(size)
            size /= 2.0
        return tuple(sizes)

    def no_finer_than(self, spacing: float) -> "Relief":
        """This grain with every band a surface at ``spacing`` cannot hold cut.

        The drawn surface and the surface a world is *collided* against have to
        agree, and the collided one is a grid of its own. A band finer than that
        grid can carry is relief a player sees and walks straight through, so it
        is held back from what is drawn as well.

        The coarsest band always survives: a surface with one band it can only
        just resolve and a surface with no grain at all are different answers,
        and the second is the one that reads as a smooth function.
        """
        floor = float(spacing) * self.samples_per_feature
        finest = min(max(self.finest, floor), self.coarsest)
        return Relief(coarsest=self.coarsest, finest=finest,
                      roughness=self.roughness,
                      samples_per_feature=self.samples_per_feature,
                      seed=self.seed, where=self.where)

    def bands(self, spacing: float) -> tuple[float, ...]:
        """The feature sizes a surface sampled every ``spacing`` metres shows."""
        reach = float(spacing) * self.samples_per_feature
        return tuple(size for size in self.wavelengths() if size >= reach)

    def amplitude(self, spacing: float, error: float) -> float:
        """How far this relief moves the ground, in metres, at one tile."""
        wanted = sum(size * self.roughness for size in self.bands(spacing))
        return float(min(wanted, max(float(error), 0.0)))

    def height(self, x: Any, z: Any, spacing: float, error: float) -> np.ndarray:
        """Metres to add to the ground at ``(x, z)``, about zero.

        ``spacing`` is how far apart the surface's samples are and ``error`` the
        tile's geometric error; between them they decide which bands appear and
        how far the ground is allowed to move. Ground ``where`` says was worked
        gets less of it, or none.
        """
        x = np.asarray(x, dtype='d')
        z = np.asarray(z, dtype='d')
        sizes = self.bands(spacing)
        total = np.zeros(np.broadcast(x, z).shape, dtype='d')
        if not sizes:
            return total
        wanted = 0.0
        for index, size in enumerate(sizes):
            weight = size * self.roughness
            if not weight:
                continue
            wanted += weight
            total += weight * (fbm(x / size, z / size,
                                   seed=self.seed + 977 * index, octaves=1)
                               - 0.5) * 2.0
        if not wanted:
            return total
        held = min(wanted, max(float(error), 0.0))
        total *= held / wanted
        if self.where is not None:
            total *= np.clip(np.asarray(self.where(x, z), dtype='d'), 0.0, 1.0)
        return total

    def over(self, height_fn: HeightFn, spacing: float,
             error: float) -> HeightFn:
        """``height_fn`` with this relief added, for a surface at ``spacing``.

        A surface too coarse to show any of the grain gets its own function
        back, so nothing is paid for a feature that could not be drawn.
        """
        if not self.bands(spacing) or not self.roughness:
            return height_fn

        def ground(x: Any, z: Any) -> Any:
            return height_fn(x, z) + self.height(x, z, spacing, error)

        return ground


def _unit(i: np.ndarray, j: np.ndarray, k: int, salt: int, seed: int) -> np.ndarray:
    """A value in [0, 1) for each integer pair ``(i, j)``, fixed by ``k``, ``salt`` and ``seed``."""
    mask = np.uint64(0xFFFFFFFFFFFFFFFF)
    with np.errstate(over='ignore'):
        n = (np.asarray(i, dtype=np.int64).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
             ^ np.asarray(j, dtype=np.int64).astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
             ^ np.uint64((k * 0x165667B19E3779F9 + salt * 0x27D4EB2F165667C5 + seed * 0x9E3779B1)
                         & 0xFFFFFFFFFFFFFFFF))
        n = (n ^ (n >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9) & mask
        n = (n ^ (n >> np.uint64(27))) * np.uint64(0x94D049BB133111EB) & mask
        n = n ^ (n >> np.uint64(31))
    return np.asarray((n >> np.uint64(11)).astype('d') / float(1 << 53))


@dataclass(frozen=True)
class RockRelief:
    """Ground that is bare rock, shaped by scraping: terraces, flat faces and steps.

    Bare rock is not a smoother or rougher version of the hillside it lies on. It is a
    block with flat faces cut into it. This builds that the way
    :func:`~OpenGLContext.scenegraph.natural.scrape` builds a boulder: the rock starts as
    a raised, slightly uneven slab, and flat discs are pressed into it, each cutting
    down to a plane (a little tilted) within its reach and leaving what lies outside. Where
    discs overlap the lowest plane wins, so the surface steps down in facets with a
    clean edge at every rim, and a fine grain is laid over them.

    The result is metres to add to the ground, from 0 where the rock gives out up to
    ``height``. It is a function of position alone, so the surface that is drawn and the
    one that is walked on are the same function, and neighbouring tiles meet exactly.

    ``where(x, z)`` is how rocky each place is, from 0 to 1; rock appears from
    ``begins`` and is whole from ``whole``, blending into the ground between, and a place
    below ``begins`` has none. ``cell`` is the width of the square that holds each
    ``scrapes`` discs, whose radius runs over ``span`` times the cell's half width and
    whose cuts are ``depth`` of the height deep; ``tilt`` is the steepest slope of a
    scraped face. ``grain`` is the height of the fine roughness, in metres. Features
    smaller than a few samples are left out of a surface sampled coarsely, as
    :class:`Relief` leaves out its bands.
    """

    where: Weight
    height: float = 0.7
    cell: float = 6.0
    scrapes: int = 2
    span: tuple[float, float] = (0.55, 1.15)
    depth: tuple[float, float] = (0.15, 0.65)
    tilt: float = 0.3
    grain: float = 0.05
    begins: float = 0.35
    whole: float = 0.7
    seed: int = 0
    #: How far above the ground bare rock stands at its lowest, in metres, which keeps
    #: the rock surface from lying in the ground it replaces.
    lift: float = 0.03
    #: Samples across a scrape's radius before it is drawn.
    samples_per_scrape: float = 3.0

    def __post_init__(self) -> None:
        if self.height <= 0.0 or self.cell <= 0.0 or self.scrapes < 0:
            raise ValueError('rock relief %r m high in cells %r m wide with %r scrapes'
                             % (self.height, self.cell, self.scrapes))
        if not 0.0 <= self.begins < self.whole <= 1.0:
            raise ValueError('rock begins at %r and is whole at %r; need 0 <= begins < whole <= 1'
                             % (self.begins, self.whole))

    def weight(self, x: Any, z: Any) -> np.ndarray:
        """How much rock each place has, from 0 to 1."""
        rocky = np.clip(np.asarray(self.where(x, z), dtype='d'), 0.0, 1.0)
        return np.asarray(smoothstep(np.clip((rocky - self.begins) / (self.whole - self.begins),
                                             0.0, 1.0)))

    def _slab(self, x: Any, z: Any) -> np.ndarray:
        """The uncut rock: a slab as high as ``height`` and a little uneven."""
        wander = fbm(np.asarray(x, 'd') / 9.0, np.asarray(z, 'd') / 9.0, seed=self.seed + 31,
                     octaves=2)
        return np.asarray(self.height * (0.8 + 0.2 * wander))

    def rock(self, x: Any, z: Any, spacing: float = 0.0) -> np.ndarray:
        """How high the rock stands above the ground at each place, where it is rock: 0 up to
        ``height``, before ``where`` is applied. ``spacing`` leaves out the scrapes a surface
        sampled that coarsely cannot hold."""
        x = np.asarray(x, dtype='d')
        z = np.asarray(z, dtype='d')
        surface = self._slab(x, z)
        ci = np.floor(x / self.cell).astype(np.int64)
        cj = np.floor(z / self.cell).astype(np.int64)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                i, j = ci + di, cj + dj
                for k in range(self.scrapes):
                    cx = (i + _unit(i, j, k, 1, self.seed)) * self.cell
                    cz = (j + _unit(i, j, k, 2, self.seed)) * self.cell
                    reach = 0.5 * self.cell * (self.span[0] + (self.span[1] - self.span[0])
                                               * _unit(i, j, k, 3, self.seed))
                    cut = self.height * (self.depth[0] + (self.depth[1] - self.depth[0])
                                         * _unit(i, j, k, 4, self.seed))
                    sx = self.tilt * (2.0 * _unit(i, j, k, 5, self.seed) - 1.0)
                    sz = self.tilt * (2.0 * _unit(i, j, k, 6, self.seed) - 1.0)
                    plane = self._slab(cx, cz) - cut + sx * (x - cx) + sz * (z - cz)
                    inside = np.hypot(x - cx, z - cz) < reach
                    if spacing:
                        inside = inside & (reach >= spacing * self.samples_per_scrape)
                    surface = np.where(inside, np.minimum(surface, plane), surface)
        if self.grain and spacing * 4.0 <= 3.2:
            for size, share in ((3.2, 1.0), (1.6, 0.5)):
                if spacing * 4.0 <= size:
                    surface = surface + self.grain * share * 2.0 * (
                        fbm(x / size, z / size, seed=self.seed + 53 + int(size * 10),
                            octaves=1) - 0.5)
        return np.asarray(np.maximum(surface, 0.0))

    def displacement(self, x: Any, z: Any, spacing: float = 0.0) -> np.ndarray:
        """Metres to add to the ground at ``(x, z)``: none off the rock, the rock's height on it.

        ``spacing`` is how far apart the surface's samples are.
        """
        found = self.weight(x, z)
        out = np.asarray(found * (self.lift + self.rock(x, z, spacing)))
        return out

    def no_finer_than(self, spacing: float) -> "RockRelief":
        """This rock; scrapes too small for a surface at ``spacing`` are left out as it is
        sampled (:meth:`rock`), so there is nothing to cut."""
        return self

    def over(self, height_fn: HeightFn, spacing: float, error: float) -> HeightFn:
        """``height_fn`` with the rock added, for a surface at ``spacing``.

        ``error`` is taken for the signature of :meth:`Relief.over` and unused: a block of
        rock is the shape of the ground, not grain inside the error a tile may be wrong by.
        """
        def ground(x: Any, z: Any) -> Any:
            return height_fn(x, z) + self.displacement(x, z, spacing)

        return ground


@dataclass(frozen=True)
class Reliefs:
    """Several reliefs as one: each is added over what the ones before it made.

    It answers where a :class:`Relief` is asked for, so a surface carries grain and bare rock
    together.
    """

    parts: tuple[Any, ...]

    def no_finer_than(self, spacing: float) -> "Reliefs":
        """Each part held to what a surface at ``spacing`` can carry."""
        return Reliefs(tuple(part.no_finer_than(spacing) for part in self.parts))

    def over(self, height_fn: HeightFn, spacing: float, error: float) -> HeightFn:
        """``height_fn`` with every part added, for a surface at ``spacing``."""
        ground = height_fn
        for part in self.parts:
            ground = part.over(ground, spacing, error)
        return ground


#: The grain a baked landscape carries: features from a stride across up to a
#: few paces, at a slope a car drives over rather than is stopped by. Anything
#: bigger belongs in the landscape's own shape.
GROUND_RELIEF = Relief()
