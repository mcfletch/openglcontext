"""What grows on the ground between the trees.

A wood with bare ground under it is trees standing on a lawn. What makes the
floor of one read as a floor is *cover*, and a floor is not one plant repeated:
it is grass and fern and nettle and shrub, each at its own density and its own
size. :class:`GroundCover` takes a set of :class:`CoverSpecies` and draws each
through the whole distance chain.

Each species is drawn at three reaches, because what the eye can tell apart
falls away with distance faster than the cost of drawing it does:

- **real geometry**, near the camera, in two levels of detail -- full mesh over
  the inner disc, a decimated one over the rest. The outer ring is most of the
  plants, so that is where the triangles are saved;
- **cards** beyond the geometry, a thinner field, fading in exactly where the
  geometry fades out;
- **coarse cards** beyond those, thinner again, out to where the haze takes over.

None of it is baked. The ground is the same everywhere and there is far too much
of it -- a metre-spaced scatter over four kilometres is sixteen million
instances -- so each rung is scattered on a *world-anchored* grid around the
camera and re-chosen as that moves
(:func:`~OpenGLContext.scenegraph.vegetation.grid.world_grid_scatter`). A cell's
position and its fate are decided by the cell's own hash, so nothing shifts or
appears as the disc recentres, and each species is salted onto a grid of its
own so no two of them contend for the same cells.

Where it grows is decided by the ground itself. The splat control map already
says where the grass and the leaf litter are, and it already has the road's
corridor painted out of them, so :func:`control_weight` turns that map into the
mask and nothing else has to know about the road.

How it is *lit* is decided by the ground as well. A terrain under a canopy is
already darkened by it -- see
:meth:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain.shade` -- and cover
that ignores that is a row of lamps on the forest floor, so ``shade`` hands the
same figure to each instance.

**The scatter is the expensive half and it touches no GL**, so a caller with a
worker thread runs :meth:`GroundCover.compute_near` there and calls
:meth:`GroundCover.apply_near` on the render thread with what came back;
:meth:`GroundCover.update` is the same work done in line. :meth:`GroundCover.select`
is the cheap per-frame half, which re-centres the drawn geometry on the live
camera so the disc never lags the walk.
"""
from __future__ import annotations

# posixpath, not os.path: these join a reference rather than open a file,
# and a baked world is as likely to be served over http as read off disk.
# Forward slashes are a path on every platform and a URL as well.
import posixpath
import zlib
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence, Union

import numpy as np

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.grid import world_grid_scatter

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

__all__ = ['CoverSpecies', 'CoverRung', 'GroundCover', 'control_weight',
           'CLUMP_RADIUS', 'CARD_RADIUS', 'FAR_RADIUS', 'COVER_JITTER',
           'CLUMP_LOD_FRAC']

#: How far real clump geometry reaches, in metres; how far the cards that
#: replace it do; and how far the coarse field beyond those runs. The clumps are
#: what someone on foot sees blades in; past them the same thing is a card, and
#: past *that* it is only the colour of the ground.
CLUMP_RADIUS = 34.0
CARD_RADIUS = 130.0
FAR_RADIUS = 700.0

#: How far the camera moves before a rung is scattered again, in metres. The
#: scatter is world-anchored, so a stale disc is not a wrong one -- it is only a
#: disc centred a little behind. The far field is a disc of several hundred
#: metres and is not worth re-scattering every few paces.
SETTLED_METRES = 10.0
FAR_SETTLED_METRES = 40.0

#: Which fraction of the clump disc the full-detail geometry covers. The outer
#: ``1 - FRAC**2`` of the area -- most of the plants -- is drawn with the coarse
#: mesh instead, which is where the vertex cost of a field like this lives.
CLUMP_LOD_FRAC = 0.45

#: Where each dither window starts, as a fraction of its outer edge. Three of
#: them: the full-detail geometry fading out into the coarse geometry, the
#: coarse geometry fading out into the cards, and the cards fading out at the
#: edge of their disc. A disc that simply stops has an edge that reads as a
#: carpet growing in as you walk.
CLUMP_FADE = 0.8

#: How much wider than the drawn disc the geometry scatter is cached, in metres.
#: :meth:`GroundCover.select` re-chooses the drawn subsets from that cache
#: against the *live* camera every frame, so the disc has to hold plants out to
#: its full radius even once its centre has fallen behind -- which is why this
#: has to be at least :data:`SETTLED_METRES`.
CLUMP_STREAM_MARGIN = 11.0

#: How much of a species' density each card rung carries. A card standing in for
#: a clump does not need to be as dense to read as continuous cover, and out
#: where a card is a few pixels across a dense field is spent for nothing.
CARD_SHARE = 0.39
FAR_SHARE = 0.01

#: How much larger the coarse far cards run. Bigger cards, fewer of them: at
#: several hundred metres what is wanted is ground colour, and a card too small
#: to resolve contributes nothing but a draw.
FAR_SCALE = 1.5

#: How far a plant may wander from its cell, as a fraction of the cell. Over 1,
#: so a plant may land in its neighbour's ground: kept inside its own, the set is
#: still a grid, and from thirty metres a grid reads as diagonal rows of evenly
#: spaced plants. Clumps and gaps are what real cover looks like.
COVER_JITTER = 1.7

#: How tall cover is by default, in metres, and how wide a card is as a
#: fraction of its height.
COVER_HEIGHT = 0.55
CARD_WIDTH = 1.25

#: How flatly the cards are lit. Cover is in its own shade most of the time, and
#: a card lit like a leaf facing the sun reads as a neon lump on the ground.
CARD_SUN = 0.42

#: Where the sun is for the clump geometry, which is lit per fragment rather
#: than by the flat term the cards use. The same direction the terrain and the
#: trees are lit from, or the floor is lit from somewhere else than the wood.
CLUMP_SUN = (-0.5, -0.72, -0.48)


@dataclass(frozen=True)
class CoverSpecies:
    """What one kind of ground cover is drawn from.

    ``card`` is the billboard texture, and is what the far field is made of.
    ``clump`` is an optional ``.glb`` of real geometry, drawn near the camera;
    without one the cover is cards all the way in, which is cheaper and reads
    acceptably from a moving vehicle.

    One ``.glb`` holds every rung of a plant against the one cutout texture they
    share, so ``clump_mesh`` says which mesh in it is the full-detail geometry
    and ``clump_far_mesh`` which is the decimated one. Named rather than
    numbered, where the bake gave them names: the order meshes are written in is
    the order the bake happened to walk the file's variants. With no
    ``clump_far_mesh`` both rungs draw the same mesh, which costs what it costs.

    ``density`` is plants per square metre before the mask thins it, ``height``
    how tall one is in metres, ``card_width`` how wide its card is as a fraction
    of that, and ``sun_level`` how flatly the card is lit.
    """

    name: str
    card: str
    clump: Optional[str] = None
    clump_mesh: Union[int, str] = 0
    clump_far_mesh: Optional[Union[int, str]] = None
    density: float = 2.2
    height: float = COVER_HEIGHT
    card_width: float = CARD_WIDTH
    sun_level: float = CARD_SUN

    def __repr__(self) -> str:
        return 'CoverSpecies(%s)' % (self.name,)

    @property
    def salt(self) -> int:
        """Which world-anchored grid this species is scattered on.

        Keyed on the name rather than on the position in a list, so adding a
        plant to a world does not move every plant after it, and a checksum
        rather than :func:`hash` because that is salted per process and the
        placement has to be the same on every machine and every run.
        """
        return int(zlib.crc32(self.name.encode('utf-8')))

    def beside(self, directory: str) -> 'CoverSpecies':
        """The same species with its files resolved against ``directory``."""
        return replace(
            self, card=posixpath.join(directory, self.card),
            clump=(None if not self.clump
                   else posixpath.join(directory, self.clump)))

    def to_json(self) -> dict:
        """This species as a baked world carries it."""
        return {'name': self.name, 'card': self.card, 'clump': self.clump,
                'clumpMesh': self.clump_mesh,
                'clumpFarMesh': self.clump_far_mesh,
                'density': self.density, 'height': self.height,
                'cardWidth': self.card_width, 'sunLevel': self.sun_level}

    @classmethod
    def from_json(cls, record: Any) -> 'CoverSpecies':
        """A species read back out of a baked world."""
        return cls(name=record['name'], card=record['card'],
                   clump=record.get('clump') or None,
                   clump_mesh=record.get('clumpMesh', 0),
                   clump_far_mesh=record.get('clumpFarMesh'),
                   density=float(record.get('density', 2.2)),
                   height=float(record.get('height', COVER_HEIGHT)),
                   card_width=float(record.get('cardWidth', CARD_WIDTH)),
                   sun_level=float(record.get('sunLevel', CARD_SUN)))


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


class CoverRung:
    """Everything one species of cover is drawn with.

    Four nodes and the scatter behind them: the two geometry levels of detail
    (absent where the species has no clump), the cards that replace them, and
    the coarse cards beyond those.
    """

    def __init__(self, species: CoverSpecies, clump_radius: float,
                 card_radius: float, far_radius: float,
                 sun: "tuple[float, float, float]") -> None:
        if not species.card:
            raise ValueError(
                "ground cover species %r has no card texture to draw with"
                % (species.name,))
        self.species = species
        #: The cards that stand in for the geometry, and the coarse field past
        #: them. The near cut is where the rung inside this one fades out.
        self.cards = InstancedBillboards(
            _nothing(), _none(), _none(), species.card,
            width=species.card_width, sun_level=species.sun_level,
            far_fade=card_radius,
            near_cut=clump_radius if species.clump else 0.0)
        self.far_cards = InstancedBillboards(
            _nothing(), _none(), _none(), species.card,
            width=species.card_width, sun_level=species.sun_level,
            far_fade=far_radius, near_cut=card_radius * CLUMP_FADE)
        #: Real geometry, when the species has a mesh to grow it from: full
        #: detail over the inner disc, decimated over the rest.
        self.clumps_near: Any = None
        self.clumps_far: Any = None
        if species.clump:
            from OpenGLContext.scenegraph.vegetation.clumps import (
                InstancedClumps, load_clump_glb,
            )
            near = load_clump_glb(species.clump, mesh=species.clump_mesh)
            far = (near if species.clump_far_mesh is None
                   else load_clump_glb(species.clump,
                                       mesh=species.clump_far_mesh))
            self.clumps_near = InstancedClumps(*near[:4], near[4], sun=sun)
            self.clumps_far = InstancedClumps(*far[:4], far[4], sun=sun)
        #: The geometry scatter, cached over a disc wider than the drawn one so
        #: :meth:`GroundCover.select` always has plants to draw out to the full
        #: radius even once the cache's centre has fallen behind the camera.
        self.cache: Optional[tuple] = None

    @property
    def nodes(self) -> "list[Any]":
        """This species' rungs, outermost first, as the scene draws them."""
        return [node for node in (self.far_cards, self.cards,
                                  self.clumps_near, self.clumps_far)
                if node is not None]

    def retune(self, clump_radius: float, card_radius: float,
               far_radius: float) -> None:
        """Point every fade window at the radii the rungs now run to.

        The coarse geometry is the complete base layer -- every plant in the
        disc, dithering out only at its edge, where the cards take over. The
        full-detail geometry is an overlay of what is inside
        ``CLUMP_LOD_FRAC`` of that, drawn first so it hides the coarse mesh
        where both are present and dithering out into it over the same window.
        Same texture on both, so the handoff has nothing to show.
        """
        self.cards.far_fade = card_radius
        self.cards.near_cut = clump_radius if self.species.clump else 0.0
        self.far_cards.far_fade = far_radius
        self.far_cards.near_cut = card_radius * CLUMP_FADE
        if self.clumps_near is None or self.clumps_far is None:
            return
        inner = clump_radius * CLUMP_LOD_FRAC
        self.clumps_near.fade_start = inner * CLUMP_FADE
        self.clumps_near.fade_end = inner
        self.clumps_far.cut_start = self.clumps_far.cut_end = 0.0
        self.clumps_far.fade_start = clump_radius * CLUMP_FADE
        self.clumps_far.fade_end = clump_radius
        for node in self.nodes:
            if node._gl is not None:
                node._commit_constants()


class GroundCover(Group):
    """Cover around the camera: geometry near it, cards beyond, haze past those.

    ``field`` is the ground it sits on and ``species`` what it is made of --
    one :class:`CoverSpecies` or a sequence of them.
    ``mask(x, z) -> weight`` says where it grows; see :func:`control_weight`.
    ``shade(x, z) -> sun`` says how much of the sun reaches it, in [0, 1].

    Call :meth:`update` once a frame with where the camera is. A caller with a
    worker thread splits that instead: :meth:`compute_near` and
    :meth:`compute_far` are pure numpy and touch no GL, :meth:`apply_near` and
    :meth:`apply_far` stage what they returned, and :meth:`select` is the cheap
    per-frame re-centring that must happen every frame either way.
    """

    def __init__(self, field: "HeightField",
                 species: "Union[CoverSpecies, Sequence[CoverSpecies]]",
                 clump_radius: float = CLUMP_RADIUS,
                 card_radius: float = CARD_RADIUS,
                 far_radius: float = FAR_RADIUS,
                 mask: Optional[Callable[[Any, Any], Any]] = None,
                 shade: Optional[Callable[[Any, Any], Any]] = None,
                 sun: "tuple[float, float, float]" = CLUMP_SUN,
                 **named: Any) -> None:
        super().__init__(**named)
        kinds = ([species] if isinstance(species, CoverSpecies)
                 else list(species))
        if not kinds:
            raise ValueError("ground cover needs at least one species to grow")
        self.field = field
        self.species = kinds
        self.clump_radius = float(clump_radius)
        self.card_radius = max(float(card_radius), float(clump_radius))
        self.far_radius = max(float(far_radius), self.card_radius)
        self.mask = mask
        self.shade = shade
        #: How many times a disc has been scattered, which is the cost a caller
        #: wondering what the cover is spending should watch.
        self.selections = 0
        self.rungs = [CoverRung(one, self.clump_radius, self.card_radius,
                                self.far_radius, sun) for one in kinds]
        # children is a VRML ChildrenTypedField descriptor that coerces a node list.
        self.children = [_drawn(node) for rung in self.rungs
                         for node in rung.nodes]
        self._near_at: Optional[np.ndarray] = None
        self._far_at: Optional[np.ndarray] = None
        self._drawn_at: Optional[tuple] = None
        self.retune()

    def rung(self, name: str) -> CoverRung:
        """The rung for the species called ``name``."""
        for rung in self.rungs:
            if rung.species.name == name:
                return rung
        raise KeyError("no cover species named %r; this ground grows %s"
                       % (name, ', '.join(repr(one.species.name)
                                          for one in self.rungs)))

    def retune(self) -> None:
        """Point every fade window at the current radii.

        Called at build, and whenever a quality setting moves a radius: the
        windows are what make one rung hand off to the next without a seam, so
        they cannot be left where a previous radius put them.
        """
        self.card_radius = max(self.card_radius, self.clump_radius)
        self.far_radius = max(self.far_radius, self.card_radius)
        for rung in self.rungs:
            rung.retune(self.clump_radius, self.card_radius, self.far_radius)

    # -- the scatter, which is pure numpy and touches no GL --------------------

    def _scatter(self, x: float, z: float, radius: float, density: float,
                 height: float, salt: int) -> tuple:
        """One disc of one species, with how much sun reaches each plant."""
        points, yaws, scales = world_grid_scatter(
            x, z, radius, density, self.field, scale_mul=height,
            jitter=COVER_JITTER, mask=self.mask, salt=salt)
        lit = (None if self.shade is None
               else np.asarray(self.shade(points[:, 0], points[:, 2]), 'f4'))
        return points, yaws, scales, lit

    def compute_near(self, x: float, z: float) -> list:
        """Scatter the geometry and the cards around ``(x, z)``. No GL.

        The geometry is scattered over a disc a margin wider than the one that
        is drawn, and cached whole; :meth:`select` picks the two drawn subsets
        out of it against the live camera. Returns what :meth:`apply_near`
        wants.
        """
        out = []
        for rung in self.rungs:
            kind = rung.species
            cards = self._scatter(x, z, self.card_radius,
                                  kind.density * CARD_SHARE, kind.height,
                                  kind.salt)
            clumps = (None if rung.clumps_near is None else self._scatter(
                x, z, self.clump_radius + CLUMP_STREAM_MARGIN, kind.density,
                kind.height, kind.salt))
            out.append((cards, clumps))
        return out

    def apply_near(self, payload: list) -> None:
        """Stage what :meth:`compute_near` produced. Render thread."""
        for rung, (cards, clumps) in zip(self.rungs, payload, strict=True):
            rung.cards.update_instances(*cards)
            rung.cache = clumps
        self._drawn_at = None                  # a new cache: re-choose from it

    def compute_far(self, x: float, z: float) -> list:
        """Scatter the coarse field that runs out to the haze. No GL."""
        return [self._scatter(x, z, self.far_radius,
                              rung.species.density * FAR_SHARE,
                              rung.species.height * FAR_SCALE,
                              rung.species.salt) for rung in self.rungs]

    def apply_far(self, payload: list) -> None:
        """Stage what :meth:`compute_far` produced. Render thread."""
        for rung, cards in zip(self.rungs, payload, strict=True):
            rung.far_cards.update_instances(*cards)

    # -- the per-frame half, which is a pair of distance masks -----------------

    def select(self, x: float, z: float) -> None:
        """Re-choose the drawn geometry from the cache, for a camera here.

        The coarse rung draws every plant within ``clump_radius`` of the *live*
        camera and the full-detail rung the subset within ``CLUMP_LOD_FRAC`` of
        that -- so the disc tracks the walk exactly, and its leading edge fades
        in through the level-of-detail band instead of jumping in density each
        time a re-scatter recentres it. Cheap enough for every frame: two
        distance masks and an instance upload.
        """
        if self._drawn_at is not None \
                and abs(x - self._drawn_at[0]) + abs(z - self._drawn_at[1]) < 0.05:
            return                             # the camera is standing still
        self._drawn_at = (x, z)
        outer = self.clump_radius ** 2
        inner = (self.clump_radius * CLUMP_LOD_FRAC) ** 2
        for rung in self.rungs:
            if rung.cache is None:
                continue
            points, yaws, scales, lit = rung.cache
            away = (points[:, 0] - x) ** 2 + (points[:, 2] - z) ** 2
            for node, within in ((rung.clumps_far, away < outer),
                                 (rung.clumps_near, away < inner)):
                node.update_instances(points[within], yaws[within],
                                      scales[within],
                                      None if lit is None else lit[within])

    # -- the whole thing in line, for a caller with no worker ------------------

    def update(self, position: Any) -> None:
        """Bring the cover up to date for a camera here; call once a frame.

        Re-scatters whichever rungs the camera has walked far enough to have
        moved off the middle of, then re-centres the drawn geometry -- which
        happens every frame, because that is what keeps the disc from lagging.
        """
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        x, z = float(at[0]), float(at[2])
        if _walked(at, self._near_at) > SETTLED_METRES:
            self.selections += 1
            self._near_at = at.copy()
            self.apply_near(self.compute_near(x, z))
        if _walked(at, self._far_at) > FAR_SETTLED_METRES:
            self._far_at = at.copy()
            self.apply_far(self.compute_far(x, z))
        self.select(x, z)


def _walked(at: np.ndarray, was: Optional[np.ndarray]) -> float:
    """How far the camera is from where a rung was last scattered, in plan."""
    if was is None:
        return float('inf')
    return float(np.hypot(at[0] - was[0], at[2] - was[2]))


def _nothing() -> np.ndarray:
    """An empty position array, for a node with nothing staged on it yet."""
    return np.zeros((0, 3), 'f4')


def _none() -> np.ndarray:
    """An empty per-instance array, to match :func:`_nothing`."""
    return np.zeros(0, 'f4')


def _drawn(geometry: Any) -> Any:
    """A vegetation node wrapped so the scenegraph will render it.

    The instanced nodes drive their own program and need no material, but the
    pass reaches geometry through a Shape and would not otherwise see them.
    """
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.material import Material
    from OpenGLContext.scenegraph.shape import Shape
    return Shape(geometry=geometry,
                 appearance=Appearance(material=Material()))
