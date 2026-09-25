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

**What is drawn is what is collided against.** The height field a world carries
is the one surface every reader agrees about -- the car, the camera, the seat of
a scattered plant -- so the grain goes into *it*, and the tiles are meshed from
the same function; the coarser levels are that surface with its finer bands left
off, which is ordinary level of detail. A band the field's own grid could not
hold would be relief a player sees and walks straight through, and
:meth:`Relief.no_finer_than` cuts those before anything draws them.

``where`` is the other half of agreeing: ground that was *worked* has no grain
in it, and a road is ground that was worked.

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
from OpenGLContext.noise import fbm

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
            raise ValueError("a feature smaller than nothing is not a feature")
        if self.coarsest < self.finest:
            raise ValueError(
                "relief runs from its coarsest feature (%r) down to its finest "
                "(%r)" % (self.coarsest, self.finest))
        if self.samples_per_feature < 2.0:
            raise ValueError(
                "a feature sampled fewer than twice is speckle, not relief")

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


#: The grain a baked landscape carries: features from a stride across up to a
#: few paces, at a slope a car drives over rather than is stopped by. Anything
#: bigger belongs in the landscape's own shape.
GROUND_RELIEF = Relief()
