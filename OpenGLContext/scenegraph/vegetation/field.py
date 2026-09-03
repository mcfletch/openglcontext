"""A forest as one node: geometry near the camera, cards beyond it.

A quarter of a million trees is not a quarter of a million objects in a
scenegraph. It is a table of positions, one instanced draw per species for the
cards that stand for the far field, and one more for the real geometry within a
few tens of metres -- with both sets re-chosen from the table whenever the camera
moves far enough to change them.

:class:`VegetationField` owns that. Give it the table and a
:class:`TreeSpecies` per kind of tree, call :meth:`update` with where the camera
is and which way it is looking, and it keeps
:class:`~OpenGLContext.scenegraph.vegetation.nearmesh.InstancedMeshLOD` and the
per-species
:class:`~OpenGLContext.scenegraph.vegetation.billboards.InstancedBillboards`
fed. The two rungs cross-fade in their own shaders over a window they share, so
a tree turns from a card into branches without a step.

Selection is skipped while the camera is nearly still, because re-choosing from
a table of a quarter of a million every frame is most of what a forest would
otherwise cost.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

import numpy as np

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD

__all__ = ['TreeSpecies', 'VegetationField', 'NEAR_RADIUS', 'FAR_RADIUS',
           'CONE_DEGREES']

#: How far from the camera trees are drawn as real geometry, in metres. Past it
#: they are cards; the two rungs cross-fade over the window their shaders share
#: (see :mod:`OpenGLContext.scenegraph.vegetation.base`), so the radius has to
#: sit outside that window rather than inside it.
NEAR_RADIUS = 90.0

#: How far cards are drawn, in metres. Far enough to cover a world of a few
#: kilometres from anywhere in it: a radius shorter than the view leaves a
#: bare ring around the forest, and the boundary of a disc seen at a shallow
#: angle reads as a ruled line across the landscape rather than as distance.
#: What is past it should be past the haze as well.
FAR_RADIUS = 3600.0

#: The half-angle of the cone the cards are chosen in, in degrees. Comfortably
#: wider than a frustum -- a 45-degree vertical field on a wide screen spreads
#: about 36 degrees to each side -- so the edge of the cone is never inside the
#: edge of the view, and a turn of the head does not arrive before the trees do.
CONE_DEGREES = 72.0

#: How close the camera has to be to where it last chose from before the choice
#: is made again, in metres, and how far the facing may turn first, as a cosine.
#: A camera holding still costs nothing; one crawling costs nothing extra.
SETTLED_METRES = 8.0
SETTLED_COSINE = 0.995

#: Cards nearer than this are drawn whichever way the camera looks: one just off
#: the edge of the view is one turn of the head away, and a card that arrives
#: after the turn reads as a tree growing.
ALWAYS_DRAWN = 140.0

#: How far outside the view a card is still submitted when the choice is made
#: against the frustum: a fixed part in metres and a part that grows with how
#: far away the card is.
#:
#: A frustum plane meets the ground in a straight line, so a card set cut
#: exactly at the view has a ruled edge across the forest the moment anything
#: disagrees about where the view is -- a streamer's own matrix against the
#: renderer's, a frame of latency, a turn of the head. The growing part is what
#: makes the slack an *angle* rather than a distance: at a kilometre out, a
#: degree is eighteen metres, and a fixed ninety would be five degrees there and
#: a whole hemisphere close up.
VIEW_MARGIN = 60.0
VIEW_SPREAD = 0.25

#: The array keys a species' parts are stored under, when it does not say.
SOLID_KEYS = ('oP', 'oN', 'oU', 'oI')
FOLIAGE_KEYS = ('bP', 'bN', 'bU', 'bI')


@dataclass(frozen=True)
class TreeSpecies:
    """One kind of tree: what it is drawn from, near and far.

    ``mesh`` is a ``.npz`` holding the geometry as named arrays. A tree is drawn
    in two parts, because they are lit and blended differently: the ``solid``
    part is the trunk and branches, opaque and textured with
    ``solid_texture``; the ``foliage`` part is the alpha-masked cards the leaves
    or needles are on, textured with ``foliage_texture``. Each is named by the
    four keys its positions, normals, texture coordinates and indices are stored
    under.

    ``impostor`` is the single card the tree becomes at a distance, and
    ``card_width`` how wide that card is as a fraction of its height.

    Paths are used as given, so a species can name files anywhere;
    :meth:`beside` resolves a set of them against one directory, which is how a
    baked world's own trees are found.
    """

    name: str
    mesh: str
    solid_texture: str
    foliage_texture: str
    impostor: str
    solid: tuple[str, ...] = SOLID_KEYS
    foliage: tuple[str, ...] = FOLIAGE_KEYS
    card_width: float = 0.55

    def __repr__(self) -> str:
        return 'TreeSpecies(%s)' % (self.name,)

    def near_entry(self) -> dict:
        """This species as :class:`InstancedMeshLOD` wants to be told it."""
        return {'npz': self.mesh,
                'o_keys': tuple(self.solid), 'o_tex': self.solid_texture,
                'b_keys': tuple(self.foliage), 'b_tex': self.foliage_texture}

    def beside(self, directory: str) -> 'TreeSpecies':
        """The same species with its files resolved against ``directory``.

        posixpath, not os.path: this joins a reference rather than opening a
        file, and a baked world is as likely to be served over http as read
        off disk. Forward slashes are a path on every platform and a URL too.
        """
        import posixpath
        return replace(
            self,
            mesh=posixpath.join(directory, self.mesh),
            solid_texture=posixpath.join(directory, self.solid_texture),
            foliage_texture=posixpath.join(directory, self.foliage_texture),
            impostor=posixpath.join(directory, self.impostor))

    def to_json(self) -> dict:
        """This species as a baked world carries it."""
        return {'name': self.name, 'mesh': self.mesh,
                'solidTexture': self.solid_texture,
                'foliageTexture': self.foliage_texture,
                'impostor': self.impostor,
                'solid': list(self.solid), 'foliage': list(self.foliage),
                'cardWidth': self.card_width}

    @classmethod
    def from_json(cls, record: Any) -> 'TreeSpecies':
        """A species read back out of a baked world."""
        return cls(name=record['name'], mesh=record['mesh'],
                   solid_texture=record['solidTexture'],
                   foliage_texture=record['foliageTexture'],
                   impostor=record['impostor'],
                   solid=tuple(record.get('solid', SOLID_KEYS)),
                   foliage=tuple(record.get('foliage', FOLIAGE_KEYS)),
                   card_width=float(record.get('cardWidth', 0.55)))


class VegetationField(Group):
    """Every tree in a world, drawn near as geometry and far as cards.

    ``positions``, ``yaws`` and ``heights`` are the whole forest -- (N,3) world
    positions of the trunk bases, yaw in radians, and height in metres, which is
    also the instance's scale. ``species_id`` says which kind each tree is, and
    defaults to dealing them round-robin.

    ``shade(x, z) -> sun`` says how much of the sun reaches each tree, in
    [0, 1] -- the terrain's own canopy shading, so a tree in the middle of a
    stand is not lit like one on the edge of it.

    ``near_radius`` is how far real geometry reaches and ``far_radius`` how far
    the cards do. ``cone_degrees`` is the half-angle of the cone the cards are
    chosen in: submitting every card in a four-kilometre forest every frame is
    most of what a forest costs, and what is behind the camera is not seen.
    """

    def __init__(self, positions: Any, yaws: Any, heights: Any,
                 species: Sequence[TreeSpecies],
                 species_id: Any = None,
                 shade: Any = None,
                 near_radius: float = NEAR_RADIUS,
                 far_radius: float = FAR_RADIUS,
                 cone_degrees: float = CONE_DEGREES,
                 **named: Any) -> None:
        super().__init__(**named)
        if not species:
            raise ValueError("a vegetation field needs at least one species")
        self.positions = np.asarray(positions, np.float32).reshape(-1, 3)
        self.yaws = np.asarray(yaws, np.float32).reshape(-1)
        self.heights = np.asarray(heights, np.float32).reshape(-1)
        if not len(self.positions) == len(self.yaws) == len(self.heights):
            raise ValueError(
                "a forest of %d trees needs %d yaws and %d heights, not %d and %d"
                % (len(self.positions), len(self.positions), len(self.positions),
                   len(self.yaws), len(self.heights)))
        if species_id is None:
            species_id = np.arange(len(self.positions)) % len(species)
        self.species = list(species)
        self.species_id = np.asarray(species_id, int).reshape(-1)
        #: How much of the sun reaches each tree, or None for full sun.
        self.shades: Optional[np.ndarray] = None
        self.near_radius = float(near_radius)
        self.far_radius = max(float(far_radius), float(near_radius))
        self.cone_cosine = math.cos(math.radians(float(cone_degrees)))
        #: How many times the forest has been re-chosen from, which is the cost
        #: a caller is watching when it wonders what a field is spending.
        self.selections = 0
        self._chosen_at: Optional[np.ndarray] = None
        self._chosen_facing: Optional[np.ndarray] = None
        self._chosen_planes: Optional[np.ndarray] = None

        self.near = InstancedMeshLOD(
            self.positions, self.yaws, self.heights,
            [entry.near_entry() for entry in self.species],
            species_id=self.species_id)
        #: One card node per species that has trees, and the tables they choose
        #: from. A species with none would be an instanced draw of nothing.
        self.impostors: list[InstancedBillboards] = []
        self._card_tables: list[tuple[np.ndarray, ...]] = []
        for index, entry in enumerate(self.species):
            mine = self.species_id == index
            if not mine.any():
                continue
            self.impostors.append(InstancedBillboards(
                self.positions[mine], self.yaws[mine], self.heights[mine],
                entry.impostor, width=entry.card_width, near_fade=True))
            self._card_tables.append((self.positions[mine], self.yaws[mine],
                                      self.heights[mine], mine))
        self.children = ([_drawn(self.near)]                # type: ignore[assignment]
                         + [_drawn(node) for node in self.impostors])
        if shade is not None:
            self.lit_by(shade)

    def lit_by(self, shade: Any) -> None:
        """Say how much of the sun reaches each tree: ``shade(x, z) -> sun``.

        Separate from the constructor because the answer usually depends on the
        forest itself -- a terrain's canopy shading is worked out *from* these
        trunks -- so the field has to exist before it can be told.
        """
        self.shades = np.asarray(
            shade(self.positions[:, 0], self.positions[:, 2]),
            np.float32).reshape(-1)
        self.near.all_shade = self.shades
        self._chosen_at = None

    @property
    def tree_count(self) -> int:
        """How many trees the forest holds."""
        return len(self.positions)

    def update(self, position: Any, facing: Any = None,
               view: Any = None) -> None:
        """Choose what each rung draws, for a camera here looking that way.

        ``view`` is the camera's view-projection matrix and is the best thing to
        give: the cards are then chosen against the frustum itself, widened by
        :data:`VIEW_MARGIN` so a turn of the head does not arrive before the
        trees do.

        ``facing`` is the direction the camera looks, and is the fallback when
        there is no matrix. It is a *cone*, which is the wrong shape for a
        frustum: a camera pitched down at a valley has the trees near it inside
        the cone and the ones along its own view outside, which draws a hard
        edge across the forest.

        With neither, the cards are chosen by distance alone -- what an
        orbiting or top-down view wants.
        """
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        planes = _planes(view)
        way = (None if facing is None or planes is not None
               else _unit(np.asarray(facing, dtype='d').reshape(-1)[:3]))
        if self._settled(at, way, planes):
            return
        self.selections += 1
        self._chosen_at = at.copy()
        self._chosen_facing = None if way is None else way.copy()
        self._chosen_planes = None if planes is None else planes.copy()
        self.near.update(float(at[0]), float(at[2]), radius=self.near_radius)
        for node, (points, yaws, heights, mine) in zip(self.impostors,
                                                       self._card_tables,
                                                       strict=True):
            keep = self._cards_in_view(points, at, way, planes)
            lit = None if self.shades is None else self.shades[mine][keep]
            node.update_instances(points[keep], yaws[keep], heights[keep], lit)

    def _settled(self, at: np.ndarray, way: Optional[np.ndarray],
                 planes: Optional[np.ndarray]) -> bool:
        """Whether the camera has moved or turned enough to change the choice."""
        if self._chosen_at is None:
            return False
        if float(np.hypot(at[0] - self._chosen_at[0],
                          at[2] - self._chosen_at[2])) > SETTLED_METRES:
            return False
        if planes is not None or self._chosen_planes is not None:
            if planes is None or self._chosen_planes is None:
                return False
            # The plane normals are the view's own axes; if they have not
            # turned, neither has the camera.
            turned = np.einsum('ij,ij->i', planes[:, :3],
                               self._chosen_planes[:, :3])
            return bool(float(turned.min()) > SETTLED_COSINE)
        if way is None or self._chosen_facing is None:
            return way is None and self._chosen_facing is None
        return bool(float(way @ self._chosen_facing) > SETTLED_COSINE)

    def _cards_in_view(self, points: np.ndarray, at: np.ndarray,
                       way: Optional[np.ndarray],
                       planes: Optional[np.ndarray]) -> np.ndarray:
        """Which of a species' cards are worth submitting this frame.

        Reach is measured in plan, because that is how far away a tree reads as
        being. What is *in view* is the frustum where there is one and a cone
        about the heading where there is not.
        """
        dx = points[:, 0] - at[0]
        dz = points[:, 2] - at[2]
        flat = dx * dx + dz * dz
        within = flat <= self.far_radius * self.far_radius
        near = flat <= ALWAYS_DRAWN ** 2
        if planes is not None:
            slack = VIEW_MARGIN + VIEW_SPREAD * np.sqrt(flat)
            inside = np.all(points @ planes[:, :3].T + planes[:, 3]
                            >= -slack[:, None], axis=1)
            return np.asarray(within & (inside | near))
        if way is None or not float(np.abs(way).sum()):
            return np.asarray(within)
        dy = points[:, 1] - at[1]
        away = flat + dy * dy
        ahead = dx * way[0] + dy * way[1] + dz * way[2]
        in_cone = (ahead > 0.0) & (ahead * ahead
                                   > self.cone_cosine ** 2 * away)
        return np.asarray(within & (in_cone | near))


def _planes(view: Any) -> Optional[np.ndarray]:
    """The six inward-facing planes of a view-projection, or None for no view."""
    if view is None:
        return None
    from OpenGLContext.loaders.tiles3d.frustum import Frustum
    matrix = np.asarray(view, dtype='d')
    if matrix.shape != (4, 4):                   # pragma: no cover - defensive
        return None
    return np.asarray(Frustum.from_matrix(matrix).planes, dtype='d')


def _unit(direction: np.ndarray) -> np.ndarray:
    """A heading as a unit vector, or nothing at all if it has no length.

    A zero heading is not an error to raise: it means the caller does not know
    which way the camera looks, and every card within reach is then the right
    answer.
    """
    length = float(np.linalg.norm(direction))
    return direction / length if length > 1e-9 else np.zeros(3, dtype='d')


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
