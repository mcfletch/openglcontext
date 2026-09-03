"""What grows on the ground between the trees.

A wood with bare ground under it is trees standing on a lawn. What makes the
floor of one read as a floor is *cover*: clumps of grass you can see the blades
of within a few tens of metres, and cards beyond that out to where the haze
takes over.

None of it is baked. The ground is the same everywhere and there is far too much
of it -- a metre-spaced scatter over four kilometres is sixteen million
instances -- so the set is scattered on a *world-anchored* grid around the
camera and re-chosen as that moves
(:func:`~OpenGLContext.scenegraph.vegetation.grid.world_grid_scatter`). A cell's
position and its fate are decided by the cell's own hash, so nothing shifts or
appears as the disc recentres.

Where it grows is decided by the ground itself. The splat control map already
says where the grass and the leaf litter are, and it already has the road's
corridor painted out of them, so :func:`control_weight` turns that map into the
mask and nothing else has to know about the road.

How it is *lit* is decided by the ground as well. A terrain under a canopy is
already darkened by it -- see
:meth:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain.shade` -- and cover
that ignores that is a row of lamps on the forest floor, so ``shade`` hands the
same figure to each instance.
"""
from __future__ import annotations

# posixpath, not os.path: these join a reference rather than open a file,
# and a baked world is as likely to be served over http as read off disk.
# Forward slashes are a path on every platform and a URL as well.
import posixpath
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

import numpy as np

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.grid import world_grid_scatter

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

__all__ = ['CoverSpecies', 'GroundCover', 'control_weight',
           'CLUMP_RADIUS', 'CARD_RADIUS', 'COVER_JITTER']

#: How far real clump geometry reaches, in metres, and how far the cards do.
#: The clumps are what a driver sees blades in; past them the same thing is a
#: card, and past *that* the ground's own texture is the cover.
CLUMP_RADIUS = 34.0
CARD_RADIUS = 130.0

#: How far the camera moves before the disc is scattered again, in metres. The
#: scatter is world-anchored, so a stale disc is not a wrong one -- it is only a
#: disc centred a little behind.
SETTLED_METRES = 6.0

#: How the cards fade: in where the clumps fade out, and out at the disc's edge,
#: as a fraction of each radius. A disc that simply stops has an edge that reads
#: as a carpet growing in as you drive.
CLUMP_FADE = 0.78

#: How far a tuft may wander from its cell, as a fraction of the cell. Over 1,
#: so a tuft may land in its neighbour's ground: kept inside its own, the set is
#: still a grid, and from thirty metres a grid reads as diagonal rows of evenly
#: spaced plants. Clumps and gaps are what real cover looks like.
COVER_JITTER = 1.7

#: How tall the cover is by default, in metres, and how wide a card is as a
#: fraction of its height.
COVER_HEIGHT = 0.55
CARD_WIDTH = 1.25

#: How flatly the cards are lit. Cover is in its own shade most of the time, and
#: a card lit like a leaf facing the sun reads as a neon lump on the ground.
CARD_SUN = 0.42


@dataclass(frozen=True)
class CoverSpecies:
    """What one kind of ground cover is drawn from.

    ``card`` is the billboard texture, and is what the far field is made of.
    ``clump`` is an optional single-mesh ``.glb`` of real blades, drawn near the
    camera; without one the cover is cards all the way in, which is cheaper and
    reads acceptably from a car.

    ``density`` is clumps per square metre before the mask thins it, and
    ``height`` how tall one is in metres.
    """

    name: str
    card: str
    clump: Optional[str] = None
    density: float = 2.2
    height: float = COVER_HEIGHT

    def __repr__(self) -> str:
        return 'CoverSpecies(%s)' % (self.name,)

    def beside(self, directory: str) -> 'CoverSpecies':
        """The same species with its files resolved against ``directory``."""
        return replace(
            self, card=posixpath.join(directory, self.card),
            clump=(None if not self.clump
                   else posixpath.join(directory, self.clump)))

    def to_json(self) -> dict:
        """This species as a baked world carries it."""
        return {'name': self.name, 'card': self.card, 'clump': self.clump,
                'density': self.density, 'height': self.height}

    @classmethod
    def from_json(cls, record: Any) -> 'CoverSpecies':
        """A species read back out of a baked world."""
        return cls(name=record['name'], card=record['card'],
                   clump=record.get('clump') or None,
                   density=float(record.get('density', 2.2)),
                   height=float(record.get('height', COVER_HEIGHT)))


def control_weight(image: Any, wanted: Sequence[str], layers: Sequence[str],
                   extent: float) -> Callable[[Any, Any], Any]:
    """A mask reading how much of ``wanted`` a splat control map has, by position.

    The control map is the one thing that already knows where the grass is,
    where the rock is and where the road's corridor was painted -- so cover
    asked to grow on the grass grows on the grass, thins into the rock and stops
    at the verge, and nothing else has to be told about any of it.

    ``layers`` is the map's own layer order, ``wanted`` the subset the cover
    grows on. Returns ``mask(x, z) -> weight`` over arrays, in [0, 1].
    """
    from PIL import Image
    pixels = np.asarray(
        (image if isinstance(image, Image.Image)
         else Image.open(image)).convert('RGBA'), dtype='d') / 255.0
    channels = [index for index, name in enumerate(layers)
                if name in set(wanted) and index < pixels.shape[2]]
    weight = (pixels[..., channels].sum(axis=-1) if channels
              else np.zeros(pixels.shape[:2]))
    size = weight.shape[0]

    def at(x: Any, z: Any) -> Any:
        u = np.clip((np.asarray(x, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        v = np.clip((np.asarray(z, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        return np.clip(weight[v, u], 0.0, 1.0)
    return at


class GroundCover(Group):
    """Grass around the camera: clumps near it, cards beyond them.

    ``field`` is the ground it sits on and ``species`` what it is made of.
    ``mask(x, z) -> weight`` says where it grows; see :func:`control_weight`.
    ``shade(x, z) -> sun`` says how much of the sun reaches it, in [0, 1].
    Call :meth:`update` once a frame with where the camera is.
    """

    def __init__(self, field: "HeightField", species: CoverSpecies,
                 clump_radius: float = CLUMP_RADIUS,
                 card_radius: float = CARD_RADIUS,
                 mask: Optional[Callable[[Any, Any], Any]] = None,
                 shade: Optional[Callable[[Any, Any], Any]] = None,
                 **named: Any) -> None:
        super().__init__(**named)
        if not species.card:
            raise ValueError("ground cover needs a card texture to draw with")
        self.field = field
        self.species = species
        self.clump_radius = float(clump_radius)
        self.card_radius = max(float(card_radius), float(clump_radius))
        self.mask = mask
        self.shade = shade
        #: How many times the disc has been scattered, which is the cost a
        #: caller wondering what the cover is spending should watch.
        self.selections = 0
        self._chosen_at: Optional[np.ndarray] = None

        self.cards = InstancedBillboards(
            np.zeros((0, 3), 'f4'), np.zeros(0, 'f4'), np.zeros(0, 'f4'),
            species.card, width=CARD_WIDTH, sun_level=CARD_SUN,
            far_fade=self.card_radius,
            near_cut=self.clump_radius if species.clump else 0.0)
        #: Real blades, when the species has a clump to grow them from.
        self.clumps: Any = None
        if species.clump:
            from OpenGLContext.scenegraph.vegetation.clumps import (
                InstancedClumps, load_clump_glb,
            )
            points, normals, uv, indices, texture = load_clump_glb(species.clump)
            self.clumps = InstancedClumps(
                points, normals, uv, indices, texture,
                fade_start=self.clump_radius * CLUMP_FADE,
                fade_end=self.clump_radius)
        self.children = [_drawn(node)                # type: ignore[assignment]
                         for node in (self.cards, self.clumps)
                         if node is not None]

    def update(self, position: Any) -> None:
        """Scatter the disc around here, if the camera has moved enough."""
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        if self._chosen_at is not None and float(np.hypot(
                at[0] - self._chosen_at[0],
                at[2] - self._chosen_at[2])) <= SETTLED_METRES:
            return
        self.selections += 1
        self._chosen_at = at.copy()
        x, z = float(at[0]), float(at[2])
        points, yaws, scales = world_grid_scatter(
            x, z, self.card_radius, self.species.density, self.field,
            scale_mul=self.species.height, jitter=COVER_JITTER, mask=self.mask)
        lit = (None if self.shade is None
               else np.asarray(self.shade(points[:, 0], points[:, 2]), 'f4'))
        self.cards.update_instances(points, yaws, scales, lit)
        if self.clumps is not None:
            near = ((points[:, 0] - x) ** 2 + (points[:, 2] - z) ** 2
                    <= self.clump_radius ** 2)
            self.clumps.update_instances(points[near], yaws[near], scales[near],
                                         None if lit is None else lit[near])


def _drawn(geometry: Any) -> Any:
    """A vegetation node wrapped so the scenegraph will render it."""
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.material import Material
    from OpenGLContext.scenegraph.shape import Shape
    return Shape(geometry=geometry,
                 appearance=Appearance(material=Material()))
