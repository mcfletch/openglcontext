"""What grows on the ground between the trees.

A forest floor is covered with several plants -- grass, fern, nettle, shrub --
each at its own density and its own size. :class:`GroundCover` takes a set of
:class:`CoverSpecies` and draws each through the whole distance chain.

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
own so no two of them contend for the same cells. Since a cell's plant never
changes, each rung keeps its scatter by the block
(:class:`~OpenGLContext.scenegraph.vegetation.grid.ScatterBlocks`): a piece of
ground is scattered once while the camera is near it, and a re-centred disc
is assembled from blocks already made.

Where it grows is decided by the ground itself. The splat control map already
says where the grass and the leaf litter are, and it already has the road's
corridor painted out of them, so :func:`control_weight` turns that map into the
mask and nothing else has to know about the road.

How it is lit is decided by the ground as well. A terrain under a canopy is
already darkened by it -- see
:meth:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain.shade` -- and
``shade`` hands the same figure to each instance, so cover is as dark as the
ground it stands on.

The scatter is the expensive half and it touches no GL, so a caller with a
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
import math
import posixpath
import threading
import weakref
import zlib
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence, Union

import numpy as np
from vrml import field
from vrml.node import Node

from OpenGLContext.loaders.documentvalues import DocumentValues, JSONObject, require_text
from OpenGLContext.loaders.resolver import contained_source
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.varied import Varied
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.grid import BLOCK_METRES, Patches, ScatterBlocks

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
#: How many scatter blocks a disc is across, at least: a wide disc is scattered
#: in wide blocks.
BLOCKS_ACROSS = 8.0

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

#: How far past its radius each geometry rung is chosen from the cache, in
#: metres, and so how far the camera moves before :meth:`GroundCover.select`
#: chooses again. The shader fades each rung out by its distance from the live
#: camera, so a plant chosen in this margin is not drawn until the camera
#: comes nearer to it.
CLUMP_SELECT_SLACK = 1.0

#: How much wider than the drawn disc the geometry scatter is cached, in metres.
#: :meth:`GroundCover.select` chooses the drawn subsets from that cache against
#: the camera, so the disc has to hold plants out to its full radius and its
#: slack even once its centre has fallen behind -- which is why this is
#: :data:`SETTLED_METRES` and :data:`CLUMP_SELECT_SLACK` together.
CLUMP_STREAM_MARGIN = SETTLED_METRES + CLUMP_SELECT_SLACK

#: How much of a species' density each card rung carries. A card standing in for
#: a clump does not need to be as dense to read as continuous cover, and out
#: where a card is a few pixels across a dense field is spent for nothing.
CARD_SHARE = 0.39
FAR_SHARE = 0.01

#: How much larger the coarse far cards run. Bigger cards, fewer of them: at
#: several hundred metres what is wanted is ground colour, and a card too small
#: to resolve contributes nothing but a draw.
FAR_SCALE = 1.5

#: How far across a bed of one species is by default, in metres. Big enough to
#: walk into and out of, small enough that a clearing holds several.
PATCH_METRES = 26.0

#: How small a plant standing where it barely belongs is, as a fraction of its
#: full size. A shrub at the dim edge of where shrubs grow is a straggler, not a
#: full-sized shrub that happens to be there -- so the same field that decides
#: whether it grows at all also decides how well.
STRAGGLER = 0.55

#: How much taller and shorter than its species a plant may be. Centred on 1, so
#: a species that says it is 0.4 m tall grows plants averaging 0.4 m: what the
#: spread is *around* has to be the figure the species states, or every plant in
#: the world is quietly smaller than the model it was scanned from.
SIZE_SPREAD = (0.7, 1.3)

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

#: Which way the sunlight travels for the clump geometry, which is lit per
#: fragment rather than by the flat term the cards use. The same direction the
#: terrain and the trees are lit by
#: (:data:`~OpenGLContext.scenegraph.terrain.ground.DEFAULT_SUN`), or the floor
#: is lit from somewhere else than the wood.
CLUMP_SUN = (-0.5, -0.72, -0.48)


class CoverSpecies(Varied, Node):
    """What one kind of ground cover is drawn from.

    ``card`` is the billboard texture, and is what the far field is made of.
    ``clump`` is an optional ``.glb`` of real geometry, drawn near the camera;
    without one the cover is cards all the way in, which is cheaper and reads
    acceptably from a moving vehicle.

    One ``.glb`` holds every rung of a plant against the one cutout texture they
    share, so ``clumpMesh`` says which mesh in it is the full-detail geometry
    and ``clumpFarMesh`` which is the decimated one: a mesh's name, or its
    position in the file written as a number where no mesh has that name. Named
    rather than numbered, where the bake gave them names: the order meshes are
    written in is the order the bake happened to walk the file's variants. With
    no ``clumpFarMesh`` one mesh is drawn over the whole disc.

    ``density`` is plants per square metre before the mask thins it, ``height``
    how tall one is in metres, ``cardWidth`` how wide its card is as a fraction
    of that, and ``sunLevel`` how flatly the card is lit.

    Undergrowth is not evenly spread: ferns stand in beds and shrubs in
    thickets, with grass through and between them. ``patchiness`` runs from 0 -- as likely here as anywhere, which is
    what a grass or a small flower wants -- to 1, gathered into beds with bare
    ground between; ``patchMetres`` is how far across one bed is.

    ``canopy`` is how much tree cover the plant grows under, as a band
    ``(least, most)`` of the terrain's own closure -- 0 on open ground, 1 with
    a crown's worth of tree over every square metre (see
    :meth:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain.canopy_cover`).
    It is what puts shrubs where the trees stand apart and along the edges of
    clearings and keeps them out of a closed stand, and what keeps a shade
    plant off open ground. Empty, the plant grows anywhere. A plant near the
    edge of its band grows, but smaller -- see :data:`STRAGGLER`.

    The *closure* rather than the shade, because the shade is clamped: past a
    certain density more trees take no more light, so a stand with gaps in it
    and a closed one are equally dark and not at all equally full.

    The field names are the keys a baked world's JSON uses (:meth:`to_json`).
    """

    PROTO = 'CoverSpecies'

    name = field.newField('name', 'SFString', 1, '')
    card = field.newField('card', 'SFString', 1, '')
    clump = field.newField('clump', 'SFString', 1, '')
    clumpMesh = field.newField('clumpMesh', 'SFString', 1, '0')
    clumpFarMesh = field.newField('clumpFarMesh', 'SFString', 1, '')
    density = field.newField('density', 'SFFloat', 1, 2.2)
    height = field.newField('height', 'SFFloat', 1, COVER_HEIGHT)
    cardWidth = field.newField('cardWidth', 'SFFloat', 1, CARD_WIDTH)
    sunLevel = field.newField('sunLevel', 'SFFloat', 1, CARD_SUN)
    patchiness = field.newField('patchiness', 'SFFloat', 1, 0.0)
    patchMetres = field.newField('patchMetres', 'SFFloat', 1, PATCH_METRES)
    canopy = field.newField('canopy', 'MFFloat', 1, list)

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

    @property
    def band(self) -> Optional[tuple]:
        """The ``canopy`` band as ``(least, most)``, or None to grow anywhere."""
        if len(self.canopy) < 2:
            return None
        return (float(self.canopy[0]), float(self.canopy[1]))

    def beside(self, directory: str) -> 'CoverSpecies':
        """A copy of this species with its files joined to ``directory``.

        The names are used as the species gives them, so this is for species
        the application itself chose. Species read out of a document go
        through :meth:`located` with the document's containment.
        """
        return self.located(lambda name: posixpath.join(directory, name))

    def located(self, where: Callable[[str], str]) -> 'CoverSpecies':
        """A copy of this species with each file it names replaced by ``where(name)``.

        An empty name (no clump) stays empty. ``where`` raising refuses the
        species.
        """
        return self.varied(**{name: where(value) if value else value
                              for name, value in (('card', self.card),
                                                  ('clump', self.clump))})

    def to_json(self) -> dict:
        """This species as a baked world carries it."""
        return {'name': self.name, 'card': self.card,
                'clump': self.clump or None,
                'clumpMesh': self.clumpMesh,
                'clumpFarMesh': self.clumpFarMesh or None,
                'density': self.density, 'height': self.height,
                'cardWidth': self.cardWidth, 'sunLevel': self.sunLevel,
                'patchiness': self.patchiness,
                'patchMetres': self.patchMetres,
                'canopy': None if self.band is None else list(self.band)}

    @classmethod
    def from_json(cls, record: JSONObject,
                  values: Optional[DocumentValues] = None) -> 'CoverSpecies':
        """A species read back out of a baked world.

        Its name and card are required, and one missing is a
        :class:`~OpenGLContext.loaders.documentvalues.DocumentError`; any other
        value that cannot be read is reported through ``values`` and is the
        default. A clump mesh is named by name or by its index in the clump.
        """
        values = values if values is not None else DocumentValues()

        def number(key: str, default: float) -> float:
            return values.number(record.get(key), default, 'cover species %s' % (key,))

        canopy = record.get('canopy')
        return cls(name=require_text(record.get('name'), 'cover species name'),
                   card=require_text(record.get('card'), 'cover species card'),
                   clump=values.text(record.get('clump') or None, '',
                                     'cover species clump'),
                   clumpMesh=_mesh_name(record.get('clumpMesh'), '0', values),
                   clumpFarMesh=_mesh_name(record.get('clumpFarMesh'), '', values),
                   density=number('density', 2.2),
                   height=number('height', COVER_HEIGHT),
                   cardWidth=number('cardWidth', CARD_WIDTH),
                   sunLevel=number('sunLevel', CARD_SUN),
                   patchiness=number('patchiness', 0.0),
                   patchMetres=number('patchMetres', PATCH_METRES),
                   canopy=list(values.vector(canopy, (), 'cover species canopy',
                                             length=2) if canopy else ()))


def _mesh_name(raw: object, default: str, values: DocumentValues) -> str:
    """A clump mesh named by a document: its name, or its index as a string."""
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw
    return str(values.integer(raw, int(default or 0), 'cover species clump mesh',
                              minimum=0))


def control_weight(image: Any, wanted: Sequence[str], layers: Sequence[str],
                   extent: float) -> Callable[[Any, Any], Any]:
    """A mask reading how much of ``wanted`` a splat control map has, by position.

    The control map is the one thing that already knows where the grass is,
    where the rock is and where the road's corridor was painted -- so cover
    asked to grow on the grass grows on the grass, thins into the rock and stops
    at the verge, and nothing else has to be told about any of it.

    ``layers`` is the map's own layer order, ``wanted`` the subset the cover
    grows on. The map covers ``extent`` metres along both axes, centred on the
    origin, whatever its proportions in pixels: its columns run along x and its
    rows along z. Returns ``mask(x, z) -> weight`` over arrays, in [0, 1].
    """
    from PIL import Image
    pixels = np.asarray(
        (image if isinstance(image, Image.Image)
         else Image.open(contained_source(image))).convert('RGBA'), dtype='d') / 255.0
    channels = [index for index, name in enumerate(layers)
                if name in set(wanted) and index < pixels.shape[2]]
    weight = (pixels[..., channels].sum(axis=-1) if channels
              else np.zeros(pixels.shape[:2]))
    rows, columns = weight.shape

    def texel(position: Any, count: int) -> Any:
        across = (np.asarray(position, 'd') + extent / 2.0) / extent
        return np.clip(across * (count - 1), 0, count - 1).astype(int)

    def at(x: Any, z: Any) -> Any:
        return np.clip(weight[texel(z, rows), texel(x, columns)], 0.0, 1.0)
    return at


class CoverRung:
    """Everything one species of cover is drawn with.

    Up to four nodes and the scatter behind them: the geometry, in two levels
    of detail where the species names two meshes, one where it names one, and
    none where it has no clump; the cards that replace it; and the coarse cards
    beyond those.
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
            width=species.cardWidth, sun_level=species.sunLevel,
            far_fade=card_radius,
            near_cut=clump_radius if species.clump else 0.0)
        self.far_cards = InstancedBillboards(
            _nothing(), _none(), _none(), species.card,
            width=species.cardWidth, sun_level=species.sunLevel,
            far_fade=far_radius, near_cut=card_radius * CLUMP_FADE)
        #: Real geometry, when the species has a mesh to grow it from:
        #: ``clumps_far`` over the whole disc, and ``clumps_near``, the full
        #: detail, over the inner part of it. A species naming one mesh draws
        #: it as ``clumps_far`` alone, and ``clumps_near`` is None.
        self.clumps_near: Any = None
        self.clumps_far: Any = None
        if species.clump:
            from OpenGLContext.scenegraph.vegetation.clumps import (
                InstancedClumps, load_clump_glb,
            )
            coarse = species.clumpFarMesh or species.clumpMesh
            far = load_clump_glb(species.clump, mesh=coarse)
            self.clumps_far = InstancedClumps(*far[:4], far[4], sun=sun)
            if coarse != species.clumpMesh:
                near = load_clump_glb(species.clump, mesh=species.clumpMesh)
                self.clumps_near = InstancedClumps(*near[:4], near[4], sun=sun)
        #: The geometry scatter, cached over a disc wider than the drawn one so
        #: :meth:`GroundCover.select` always has plants to draw out to the full
        #: radius even once the cache's centre has fallen behind the camera.
        self.cache: Optional[tuple] = None
        #: Where this species gathers itself, and what that costs the grid it
        #: is scattered on -- see
        #: :class:`~OpenGLContext.scenegraph.vegetation.grid.Patches`.
        self.patches = Patches(species.patchiness, species.patchMetres,
                               species.salt)

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
        Same texture on both, so the handoff has nothing to show. A node
        already drawn is sent its new windows.
        """
        self.cards.far_fade = card_radius
        self.cards.near_cut = clump_radius if self.species.clump else 0.0
        self.far_cards.far_fade = far_radius
        self.far_cards.near_cut = card_radius * CLUMP_FADE
        if self.clumps_far is not None:
            self.clumps_far.cut_start = self.clumps_far.cut_end = 0.0
            self.clumps_far.fade_start = clump_radius * CLUMP_FADE
            self.clumps_far.fade_end = clump_radius
        if self.clumps_near is not None:
            inner = clump_radius * CLUMP_LOD_FRAC
            self.clumps_near.fade_start = inner * CLUMP_FADE
            self.clumps_near.fade_end = inner
        for node in self.nodes:
            node.refresh_constants()


class GroundCover(Group):
    """Cover around the camera: geometry near it, cards beyond, haze past those.

    ``field`` is the ground it sits on and ``species`` what it is made of --
    one :class:`CoverSpecies` or a sequence of them, held in the node's
    ``species`` field and read when the cover is built.
    ``mask(x, z) -> weight`` says where it grows; see :func:`control_weight`.
    ``holes(x, z) -> mask`` says where the ground is not there -- over a
    tunnel's bore, say. A height field answers with a height everywhere,
    including inside an opening cut through it, so cover seated on that answer
    alone stands in mid-air in the portal. Hand this the same callable the
    terrain and its colliders were given and the three agree about where the
    ground is. It may be set after the cover is built, which is what a game
    reading its roads after its ground needs.
    ``shade(x, z) -> sun`` says how much of the sun reaches it, in [0, 1].
    ``canopy(x, z) -> closure`` says how much tree cover stands over it, which
    is what a species' own ``canopy`` band is read against -- it is how a wood
    comes to have thickets where the trees thin out and a bare floor where they
    do not.

    Call :meth:`update` once a frame with where the camera is. A caller with a
    worker thread splits that instead: :meth:`compute_near` and
    :meth:`compute_far` are pure numpy and touch no GL, :meth:`apply_near` and
    :meth:`apply_far` stage what they returned, and :meth:`select` is the cheap
    per-frame re-centring that must happen every frame either way.

    With ``background`` the scatter runs on a worker thread of the cover's own.
    :meth:`shutdown` stops it; a cover that is collected stops it as well.
    """

    species = field.newField('species', 'MFNode', 1, list)

    def __init__(self, field: "HeightField",
                 species: "Union[CoverSpecies, Sequence[CoverSpecies]]",
                 clump_radius: float = CLUMP_RADIUS,
                 card_radius: float = CARD_RADIUS,
                 far_radius: float = FAR_RADIUS,
                 mask: Optional[Callable[[Any, Any], Any]] = None,
                 holes: Optional[Callable[[Any, Any], Any]] = None,
                 shade: Optional[Callable[[Any, Any], Any]] = None,
                 canopy: Optional[Callable[[Any, Any], Any]] = None,
                 sun: "tuple[float, float, float]" = CLUMP_SUN,
                 background: bool = False,
                 **named: Any) -> None:
        super().__init__(**named)
        kinds = ([species] if isinstance(species, CoverSpecies)
                 else list(species))
        if not kinds:
            raise ValueError("ground cover needs at least one species to grow")
        self.field = field
        #: Each rung's scatter, kept by the block: see :meth:`_scatter`.
        self._blocks: "dict[tuple, tuple[tuple, ScatterBlocks]]" = {}
        self._scattered = 0
        self._counting = threading.Lock()
        self._near_at: Optional[np.ndarray] = None
        self._far_at: Optional[np.ndarray] = None
        self.species = kinds
        self.clump_radius = float(clump_radius)
        self.card_radius = max(float(card_radius), float(clump_radius))
        self.far_radius = max(float(far_radius), self.card_radius)
        self.mask = mask
        #: Where the ground is not there, so nothing is seated on it. Kept
        #: apart from :attr:`mask`, which says what grows on the ground there
        #: is: an opening is not a kind of ground a plant does badly on.
        self.holes = holes
        self.shade = shade
        #: How much tree cover stands over a place, which is what decides what
        #: grows there rather than how it is lit.
        self.canopy = canopy
        #: How many times a disc has been scattered, which is the cost a caller
        #: wondering what the cover is spending should watch.
        self.selections = 0
        self._density_scale = 1.0
        #: Whether :meth:`update` scatters on a worker thread; see
        #: :class:`~OpenGLContext.scenegraph.vegetation.streaming.BackgroundCompute`.
        self.background = bool(background)
        self._worker: Any = None
        self._stop_worker: Optional[weakref.finalize] = None
        self.rungs = [CoverRung(one, self.clump_radius, self.card_radius,
                                self.far_radius, sun) for one in kinds]
        # children is a VRML ChildrenTypedField descriptor that coerces a node list.
        self.children = [_drawn(node) for rung in self.rungs
                         for node in rung.nodes]
        self._drawn_at: Optional[tuple] = None
        self.retune()

    def _told(self, name: str, value: Any) -> None:
        """Keep ``value`` as ``name``, and scatter everything again with it."""
        self.__dict__['_' + name + '_fn'] = value
        # A new table rather than an emptied one: a scatter on a worker keeps
        # the table it began with, so what it makes from the old value is
        # left there rather than put into this one.
        self._blocks = {}
        self._near_at = self._far_at = None

    @property
    def mask(self) -> Optional[Callable[[Any, Any], Any]]:
        """Where it grows: ``mask(x, z) -> weight``."""
        return self.__dict__.get('_mask_fn')

    @mask.setter
    def mask(self, value: Optional[Callable[[Any, Any], Any]]) -> None:
        self._told('mask', value)

    @property
    def holes(self) -> Optional[Callable[[Any, Any], Any]]:
        """Where the ground is not there: ``holes(x, z) -> mask``."""
        return self.__dict__.get('_holes_fn')

    @holes.setter
    def holes(self, value: Optional[Callable[[Any, Any], Any]]) -> None:
        self._told('holes', value)

    @property
    def shade(self) -> Optional[Callable[[Any, Any], Any]]:
        """How much sun reaches it: ``shade(x, z) -> sun``."""
        return self.__dict__.get('_shade_fn')

    @shade.setter
    def shade(self, value: Optional[Callable[[Any, Any], Any]]) -> None:
        self._told('shade', value)

    @property
    def canopy(self) -> Optional[Callable[[Any, Any], Any]]:
        """How much tree cover stands over it: ``canopy(x, z) -> closure``."""
        return self.__dict__.get('_canopy_fn')

    @canopy.setter
    def canopy(self, value: Optional[Callable[[Any, Any], Any]]) -> None:
        self._told('canopy', value)

    @property
    def density_scale(self) -> float:
        """A multiplier on every species' density, which is what a quality
        setting moves: a machine that cannot draw this much cover wants less of
        all of it, in proportion, rather than a different set of plants. A new
        value is scattered at the next :meth:`update`, wherever the camera is."""
        return self._density_scale

    @density_scale.setter
    def density_scale(self, value: float) -> None:
        self._density_scale = float(value)
        self._near_at = self._far_at = None

    @property
    def scattered(self) -> int:
        """How many blocks of ground have been scattered, over this cover's life.

        Each place is scattered once while the camera stays near it, so this
        grows with the ground newly reached rather than with the distance
        driven over ground already covered.
        """
        return self._scattered

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
        they cannot be left where a previous radius put them. The discs are
        scattered again at the new radii at the next :meth:`update`.
        """
        self.card_radius = max(self.card_radius, self.clump_radius)
        self.far_radius = max(self.far_radius, self.card_radius)
        self._near_at = self._far_at = None
        self._drawn_at = None
        for rung in self.rungs:
            rung.retune(self.clump_radius, self.card_radius, self.far_radius)

    # -- the scatter, which is pure numpy and touches no GL --------------------

    def _suits(self, rung: CoverRung) -> Callable[[Any, Any], Any]:
        """How well one species does at a place, in [0, 1].

        Four things at once, because they all answer the same question and the
        scatter can only be told once: the ground's own mask (where cover may
        grow at all), the openings cut through it (where there is no ground to
        grow on), the species' beds, and the canopy light it wants. A plant
        scores 0 where any of them says no.
        """
        ground, patches, opened = self.mask, rung.patches, self.holes
        band, closure = rung.species.band, self.canopy

        def at(x: Any, z: Any) -> Any:
            fit = patches.weight(x, z)
            if ground is not None:
                fit = fit * np.clip(np.asarray(ground(x, z), 'd'), 0.0, 1.0)
            if opened is not None:
                fit = fit * ~np.asarray(opened(x, z), dtype=bool)
            if band is not None and closure is not None:
                fit = fit * _band(np.asarray(closure(x, z), 'd'), band)
            return fit
        return at

    def _scatter(self, rung: CoverRung, role: str, x: float, z: float,
                 radius: float, density: float, height: float) -> tuple:
        """One disc of one species, with how much sun reaches each plant.

        Every plant is decided by its own cell of a world-anchored grid, so the
        scatter of a piece of ground never changes: it is kept by the block
        (:class:`~OpenGLContext.scenegraph.vegetation.grid.ScatterBlocks`), and
        a disc is assembled from the blocks it reaches. A block is scattered
        the first time a disc reaches it, with its plants' sizes and light.
        Changing the mask, the holes, the shade or the canopy scatters
        everything again.
        """
        # The table as it is now: one the render thread replaces while this
        # runs keeps what this makes out of the new one.
        blocks = self._blocks
        slot = (id(rung), role)
        # A block a fraction of the disc's width, so a disc is a few dozen
        # of them however far it reaches.
        metres = max(BLOCK_METRES, radius / BLOCKS_ACROSS)
        key = (float(density), float(height), metres)
        held = blocks.get(slot)
        if held is None or held[0] != key:
            kind = rung.species
            held = (key, ScatterBlocks(
                rung.patches.density_for(density), self.field,
                scale_mul=height, jitter=COVER_JITTER, mask=self._suits(rung),
                salt=kind.salt, scale_range=SIZE_SPREAD,
                finish=self._finisher(rung), metres=metres))
            blocks[slot] = held
        built = held[1].built
        found = held[1].disc(x, z, radius)
        with self._counting:
            self._scattered += held[1].built - built
        return found if len(found) == 4 else (*found, None)

    def _finisher(self, rung: CoverRung) -> Callable[..., tuple]:
        """What a block's plants are given besides their places: size and light."""
        band, canopy, shade = rung.species.band, self.canopy, self.shade

        def finish(points: np.ndarray, yaws: np.ndarray,
                   scales: np.ndarray) -> tuple:
            if band is not None and canopy is not None and len(points):
                # A plant at the edge of the cover it wants is a straggler
                # rather than a full-sized one that happens to be there.
                fit = _band(np.asarray(canopy(points[:, 0], points[:, 2]), 'd'),
                            band)
                scales = (scales * (STRAGGLER + (1.0 - STRAGGLER) * fit)
                          ).astype('f4')
            if shade is None:
                return points, yaws, scales
            return (points, yaws, scales,
                    np.asarray(shade(points[:, 0], points[:, 2]), 'f4').reshape(-1))
        return finish

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
            density = kind.density * self.density_scale
            cards = self._scatter(rung, 'cards', x, z, self.card_radius,
                                  density * CARD_SHARE, kind.height)
            clumps = (None if rung.clumps_far is None else self._scatter(
                rung, 'clumps', x, z, self.clump_radius + CLUMP_STREAM_MARGIN, density,
                kind.height))
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
        return [self._scatter(rung, 'far', x, z, self.far_radius,
                              rung.species.density * self.density_scale
                              * FAR_SHARE,
                              rung.species.height * FAR_SCALE)
                for rung in self.rungs]

    def apply_far(self, payload: list) -> None:
        """Stage what :meth:`compute_far` produced. Render thread."""
        for rung, cards in zip(self.rungs, payload, strict=True):
            rung.far_cards.update_instances(*cards)

    # -- the per-frame half, which is a pair of distance masks -----------------

    def select(self, x: float, z: float) -> None:
        """Choose the drawn geometry from the cache, for a camera here.

        The coarse rung draws every plant within ``clump_radius`` of the
        camera and the full-detail rung the subset within ``CLUMP_LOD_FRAC`` of
        that -- so the disc tracks the walk, and its leading edge fades in
        through the level-of-detail band instead of jumping in density each
        time a re-scatter recentres it. Each subset reaches
        :data:`CLUMP_SELECT_SLACK` further, and is chosen again only once the
        camera has moved that far: the shader's fade, measured from the live
        camera, hides what is chosen early, so a walk copies and uploads the
        subsets every metre rather than every frame.
        """
        if self._drawn_at is not None and math.hypot(
                x - self._drawn_at[0], z - self._drawn_at[1]) < CLUMP_SELECT_SLACK:
            return
        self._drawn_at = (x, z)
        outer = (self.clump_radius + CLUMP_SELECT_SLACK) ** 2
        inner = (self.clump_radius * CLUMP_LOD_FRAC + CLUMP_SELECT_SLACK) ** 2
        for rung in self.rungs:
            if rung.cache is None:
                continue
            points, yaws, scales, lit = rung.cache
            away = (points[:, 0] - x) ** 2 + (points[:, 2] - z) ** 2
            for node, reach in ((rung.clumps_far, outer),
                                (rung.clumps_near, inner)):
                if node is None:
                    continue
                within = away < reach
                node.update_instances(points[within], yaws[within],
                                      scales[within],
                                      None if lit is None else lit[within])

    # -- scatter and selection in line, for a caller with no worker -----------

    def update(self, position: Any) -> None:
        """Bring the cover up to date for a camera here; call once a frame.

        Re-scatters whichever rungs the camera has walked far enough to have
        moved off the middle of, then re-centres the drawn geometry
        (:meth:`select`), which is what keeps the disc from lagging.

        With :attr:`background` the scatter is handed to a worker thread and
        what it made is staged on a later call, so no frame waits for it.
        """
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        x, z = float(at[0]), float(at[2])
        near = _walked(at, self._near_at) > SETTLED_METRES
        far = _walked(at, self._far_at) > FAR_SETTLED_METRES
        if near:
            self.selections += 1
            self._near_at = at.copy()
        if far:
            self._far_at = at.copy()
        if near or far:
            if self.background:
                self._background().request(x, z, near, far)
            else:
                self._apply_both(self._compute_both(x, z, near, far))
        if self._worker is not None:
            self._worker.drain()
        self.select(x, z)

    def _compute_both(self, x: float, z: float, near: bool, far: bool) -> tuple:
        return (self.compute_near(x, z) if near else None,
                self.compute_far(x, z) if far else None)

    def _apply_both(self, payload: tuple) -> None:
        near, far = payload
        if near is not None:
            self.apply_near(near)
        if far is not None:
            self.apply_far(far)

    def _scatter_failed(self, args: tuple, error: BaseException) -> None:
        """Ask again, on the next update, for what a background scatter failed to make."""
        _x, _z, near, far = args
        if near:
            self._near_at = None
        if far:
            self._far_at = None

    def _background(self) -> Any:
        """The worker thread, started on first use.

        It holds the cover weakly, so a cover nothing else holds is collected
        and its worker stopped with it.
        """
        if self._worker is None:
            from OpenGLContext.scenegraph.vegetation.streaming import BackgroundCompute
            owner = weakref.ref(self)

            def compute(*args: Any) -> Any:
                cover = owner()
                return None if cover is None else cover._compute_both(*args)

            def apply(payload: Any) -> None:
                cover = owner()
                if cover is not None and payload is not None:
                    cover._apply_both(payload)

            def failed(args: tuple, error: BaseException) -> None:
                cover = owner()
                if cover is not None:
                    cover._scatter_failed(args, error)
            self._worker = BackgroundCompute(
                compute, apply, merge=_either, name='ground-cover',
                failed=failed)
            self._stop_worker = weakref.finalize(self, self._worker.stop)
        return self._worker

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for a background scatter to finish; whether it did in time.

        What it made is staged by the next :meth:`update`. A cover scattering
        in line has nothing to wait for.
        """
        return True if self._worker is None else bool(self._worker.wait(timeout))

    def shutdown(self) -> None:
        """Stop the background scatter's thread, if there is one."""
        if self._stop_worker is not None:
            self._stop_worker()
            self._stop_worker = None
        self._worker = None


def _either(old: tuple, new: tuple) -> tuple:
    """Two scatter requests as one: the newer place, and either's rungs."""
    return (new[0], new[1], old[2] or new[2], old[3] or new[3])


def _band(value: Any, limits: Any) -> Any:
    """How far inside ``(low, high)`` a value is, in [0, 1], with soft edges.

    1 across the middle of the band and falling to 0 at each end over a fifth of
    its width, so a species thins out of the light it wants rather than stopping
    at a line -- a hard edge here would draw a contour across the wood.
    """
    low, high = float(limits[0]), float(limits[1])
    edge = max((high - low) * 0.2, 1e-6)
    value = np.asarray(value, 'd')
    rising = np.clip((value - low) / edge, 0.0, 1.0)
    falling = np.clip((high - value) / edge, 0.0, 1.0)
    inside = np.minimum(rising, falling)
    return inside * inside * (3.0 - 2.0 * inside)     # smoothstep, no crease


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
