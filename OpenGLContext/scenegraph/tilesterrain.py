"""TilesTerrain: a scenegraph node that streams an OGC 3D Tiles terrain.

Mounts as a `Group` whose children are the tile subtrees currently selected for the
camera. Each frame the owning context calls `update_for_camera(camera,
viewport_height)`: the node runs one streaming tick (traverse -> load -> upload ->
evict, with coarse-parent fallback) and replaces its `children` with the resulting
drawables, which the render pass then re-integrates and draws.

Loading and glTF parsing happen on background worker threads; only the (cheap) mount
and the draw run on the GL thread.

A world of a few kilometres can carry its whole landscape as a *field* rather
than as a tree of ground tiles -- a height image and a splat control map beside
the tileset, named from its ``extras.terrain`` (written by
``OpenGLContext_editor.bake.field``). Where that is present the node builds the
:class:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField` and mounts a
:class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain` for it, permanently,
beside the tiles that still stream. :attr:`field` is then the ground: what a
camera is clamped to, and what
:class:`~OpenGLContext.physics.heightfield.HeightFieldColliders` builds colliders
from.
"""
import io
import json
import math
import os
from typing import Any, Callable, Optional

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.gltf_uploader import (
    make_tile_loader,
    GLTileUploader,
)


class TilesTerrain(Group):
    """A streamed 3D Tiles terrain mounted as a scenegraph group.

    `tileset_path` is a local path or an http(s) URL; content and any external
    (nested) tilesets resolve against it, and remote payloads are cached under
    `cache_dir` (default: the per-user cache dir).

    `field_terrain` and `vegetation` mount the landscape and the forest a world
    carries beside its tiles, when it carries them; turn either off in a tool
    that wants only what streams and should not pay to decode them.
    """

    #: What a world's ground carries, before it is mounted. :attr:`holes` reads
    #: them to pass an opening on, and a terrain is asked for its holes before
    #: it is asked for anything else.
    field: Any = None
    ground: Any = None
    vegetation: Any = None
    cover: Any = None
    zones: Any = None

    def __init__(self, tileset_path: str, memory_budget: int = 256 * 1024 * 1024,
                 max_sse: float = 16.0, fovy: Optional[float] = None,
                 prefetch_factor: float = 2.0,
                 max_uploads_per_update: int = 4, workers: int = 2,
                 physics_world: Any = None,
                 recenter: bool = True, cache_dir: Optional[str] = None,
                 field_terrain: bool = True, vegetation: bool = True,
                 **named: Any) -> None:
        super().__init__(**named)
        if fovy is None:
            fovy = math.radians(45.0)
        self.fovy = fovy
        doc = json.loads(fetch.read_bytes(tileset_path, cache_dir=cache_dir))
        if fetch.is_url(tileset_path):
            base_uri = fetch.dir_of(tileset_path)
        else:
            base_uri = os.path.dirname(os.path.abspath(tileset_path)) + os.sep

        def resolver(uri: str) -> Any:
            return json.loads(fetch.read_bytes(uri, cache_dir=cache_dir))

        tileset = build_runtime_tileset(doc, base_uri=base_uri, recenter=recenter,
                                        resolve_external=resolver)
        self.tileset = tileset
        on_drawn = on_evicted = None
        self.colliders = None
        if physics_world is not None:
            from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
            self.colliders = TerrainColliders(physics_world)
            # Driven by what is *drawn* rather than by what is resident: a
            # cached parent's ground is the same ground at another resolution,
            # and left in the physics world it is a second surface for a car to
            # catch a step on.
            on_drawn = self.colliders.on_drawn
            on_evicted = self.colliders.on_evicted
        self.runtime = TilesetRuntime(
            tileset, make_tile_loader(cache_dir=cache_dir), GLTileUploader(),
            memory_budget=memory_budget, fovy=fovy, max_sse=max_sse,
            prefetch_factor=prefetch_factor,
            max_uploads_per_update=max_uploads_per_update, workers=workers,
            on_evicted=on_evicted, on_drawn=on_drawn,
        )
        #: The landscape, when this world carries one as a field; None when its
        #: ground streams as tiles like everything else.
        self.field: Any = None
        #: Whether the ground the player sees comes from the tiles rather than
        #: from the field. The field is still there either way: it is what the
        #: world is collided against and clamped to.
        self.drawn_as_tiles = False
        #: The node that draws it.
        self.ground: Any = None
        self._field_node: Any = None
        extras = doc.get('extras') or {}
        if field_terrain and extras.get('terrain'):
            self._mount_field(extras['terrain'], base_uri, cache_dir)
        #: The forest, when this world carries one; None when it has no trees or
        #: bakes them into its tiles.
        self.vegetation: Any = None
        #: What grows on the ground between the trees, when a world names it.
        self.cover: Any = None
        if vegetation and extras.get('vegetation'):
            self._mount_vegetation(extras['vegetation'], base_uri, cache_dir)
        if self.ground is not None and self.vegetation is not None:
            # A splat terrain bakes a canopy term into its static shading, and
            # this is the one place that knows both where the ground is and
            # where the trees on it are. Unwired, the floor of a wood is lit
            # like an open field -- and so is everything standing on it, which
            # is why the forest is then told the same figure.
            self.ground.canopy = self.vegetation.positions
            self.vegetation.lit_by(self.ground.shade)
        if vegetation and extras.get('vegetation'):
            self._mount_cover(extras['vegetation'].get('cover'), base_uri,
                              extras.get('terrain'))
        #: The world's zones, when it names a document of them: the loaded
        #: :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`, whose
        #: ``zones`` and ``sounds`` an application may want. Its group is
        #: mounted with the landscape, so the pass finds the zones in it.
        self.zones: Any = None
        self._zone_node: Any = None
        if extras.get('zones'):
            self._mount_zones(extras['zones'], base_uri, cache_dir)
        if self.drawn_as_tiles and self.ground is not None:
            # What the tiles' ground is drawn with is what the field's ground is
            # made of: one blend, one control map, one baked light, whichever
            # mesh carries it. Taken here rather than at the mount, because the
            # light is not baked until the canopy over it is known.
            self.runtime.uploader.ground = self.ground.ground
        self._mounted = [node for node in (self._field_node, self.cover,
                                           self.vegetation, self._zone_node)
                         if node is not None]
        self.children = list(self._mounted)

    def _mount_field(self, record: Any, base_uri: str,
                     cache_dir: Optional[str]) -> None:
        """Build the field this world carries, and the node that draws it.

        A world whose ``terrain`` record says its ground is ``drawn`` by the
        *tiles* still builds the field, and still builds what the ground is made
        of from it -- the layers, the control map, the light baked into the
        landscape. What it does not do is draw it: the tiles carry the ground
        there, meshed and detailed when the world was baked, and they are drawn
        with that same shading. The field is then what the world is *collided*
        against, walked on and planted on, which is the surface that must not
        change under a wheel as a tile refines.
        """
        from OpenGLContext.scenegraph.terrain.heightfield import HeightField
        from OpenGLContext.scenegraph.terrain.splat import SplatTerrain
        layers = list(record.get('layers') or ())
        if not layers:
            raise ValueError(
                "a world's terrain record names no ground materials, so there "
                "is nothing to draw it with")
        self.field = HeightField.from_image(
            _beside(base_uri, record['height'], cache_dir),
            int(record['resolution']), float(record['extent']),
            float(record['relief']), base=float(record.get('base', 0.0)))
        # Wrapped in a Shape: the splat terrain drives its own program, but the
        # render pass reaches geometry through a Shape and would not otherwise
        # see it at all.
        from OpenGLContext.scenegraph.appearance import Appearance
        from OpenGLContext.scenegraph.material import Material
        from OpenGLContext.scenegraph.shape import Shape
        self.ground = SplatTerrain(
            self.field, layers, _beside(base_uri, record['control'], cache_dir))
        self.drawn_as_tiles = str(record.get('drawn') or 'field') == 'tiles'
        self._field_node = None if self.drawn_as_tiles else Shape(
            geometry=self.ground, appearance=Appearance(material=Material()))

    @property
    def holes(self) -> "Optional[Callable[[Any, Any], Any]]":
        """Where the ground is not there — over a tunnel's bore, say.

        Settable after the terrain is built, and it has to be: a game reads a
        tileset to stand the ground up and reads it again to find the roads, and
        only the roads know where a bore runs. The mesh is not built until the
        first draw, so anything set before then is in time.

        Hand the same callable to
        :class:`~OpenGLContext.physics.heightfield.HeightFieldColliders` and
        what is drawn and what is driven on are the same surface. Whatever
        this terrain grows is told as well: a height field answers with a
        height inside an opening as readily as outside one, so cover seated on
        that answer alone stands in the portal in mid-air.
        """
        return None if self.ground is None else self.ground.holes

    @holes.setter
    def holes(self, holes: "Optional[Callable[[Any, Any], Any]]") -> None:
        if self.ground is not None:
            self.ground.holes = holes
        if self.cover is not None:
            self.cover.holes = holes

    def _mount_vegetation(self, record: Any, base_uri: str,
                          cache_dir: Optional[str]) -> None:
        """Build the forest this world carries from its table and its species."""
        import numpy as np

        from OpenGLContext.scenegraph.vegetation.field import (
            TreeSpecies, VegetationField,
        )
        named = list(record.get('species') or ())
        if not named:
            raise ValueError(
                "a world's vegetation record names no species, so there is "
                "nothing to draw its trees as")
        beside = base_uri if fetch.is_url(base_uri) else base_uri.rstrip(os.sep)
        species = [TreeSpecies.from_json(entry).beside(beside)
                   for entry in named]
        table = np.load(_beside(base_uri, record['trees'], cache_dir))
        self.vegetation = VegetationField(
            table['positions'], table['yaws'], table['heights'], species,
            species_id=table['species'])

    def _mount_zones(self, record: Any, base_uri: str,
                     cache_dir: Optional[str]) -> None:
        """Load the world's zones, from the glTF document its extras name.

        ``record`` is ``{"document": "zones.gltf"}``: a document of
        ``OGLC_zone`` nodes and whatever they name -- emitters and their
        audio, lights -- in the world's own coordinates, beside the tileset.
        See ``docs/zones.rst``.
        """
        from OpenGLContext.loaders.gltf import loader
        name = record.get('document') if isinstance(record, dict) else record
        if not name:
            return
        if fetch.is_url(base_uri):
            self.zones = loader.load_gltf_url(base_uri + name, cache_dir=cache_dir)
        else:
            self.zones = loader.load_gltf(os.path.join(base_uri, name))
        self._zone_node = self.zones.group

    def _mount_cover(self, record: Any, base_uri: str,
                     terrain: Any) -> None:
        """Build the ground cover this world names, if it has ground for it.

        Cover sits on a height field and grows where the splat control map says
        its layers are -- which is also, without anything here knowing about
        roads, where the road's corridor is not. It is lit by the same shading
        the terrain under it carries, so a clearing and a forest floor are as
        different for the grass as they are for the ground.

        A world names one kind of plant or a set of them. The set is the record
        with a ``species`` list in it; the bare record is the one plant, which
        is what a world baked before there were sets of them carries.
        """
        if not record or self.field is None or self.ground is None:
            return
        from OpenGLContext.scenegraph.vegetation.cover import (
            CoverSpecies, GroundCover, control_weight,
        )
        beside = base_uri if fetch.is_url(base_uri) else base_uri.rstrip(os.sep)
        named = record.get('species')
        species = [CoverSpecies.from_json(entry).beside(beside)
                   for entry in (named if named is not None else [record])]
        wanted = list(record.get('on') or ())
        mask = (control_weight(self.ground.control, wanted,
                               self.ground.layers, self.field.extent)
                if wanted else None)
        # Scattered on a worker: a streamed world is driven or flown over,
        # and the ground newly reached is scattered every few frames.
        self.cover = GroundCover(self.field, species, mask=mask,
                                 shade=self.ground.shade, background=True)

    def update_for_camera(self, camera: Any, viewport_height: float,
                          max_sse: Optional[float] = None,
                          view_projection: Any = None) -> Any:
        """Run one streaming tick and update the visible tile children.

        `view_projection` (a 4x4 view-projection matrix) enables frustum culling so
        only tiles in view are refined and streamed; omit it to consider all tiles by
        distance.
        """
        drawables = self.runtime.update(camera, viewport_height, max_sse=max_sse,
                                        view_projection=view_projection)
        # What a world carries beside its tiles -- its landscape, its forest --
        # is mounted once and stays, so it leads the child list rather than
        # being swept away with the visible set.
        if self._mounted:
            drawables = list(self._mounted) + list(drawables)
        if self.vegetation is not None:
            self.vegetation.update(camera, view=view_projection,
                                   facing=_facing(view_projection))
        if self.cover is not None:
            self.cover.update(camera)
        # Preserve node identity for the pass's add/remove observers: only rewrite
        # `children` when the visible set actually changes.
        if list(self.children) != drawables:
            # children is a VRML ChildrenTypedField descriptor that coerces a node list.
            self.children = drawables
        return drawables

    def wait_for_loads(self, timeout: float = 5.0) -> Any:
        """Wait for the tiles asked for, and the cover's scatter, to be ready.

        Answers what the tile runtime's own wait answers. What the cover
        scattered is staged by the next :meth:`update_for_camera`.
        """
        loaded = self.runtime.wait_for_loads(timeout=timeout)
        if self.cover is not None:
            self.cover.wait(timeout)
        return loaded

    def shutdown(self) -> None:
        """Stop the tile loaders and the cover's scatter thread."""
        self.runtime.shutdown()
        if self.cover is not None:
            self.cover.shutdown()


def _facing(view_projection: Any) -> Any:
    """Which way the camera looks, out of its view-projection matrix.

    The near plane of a frustum is the sum of the matrix's last two rows, and
    its normal points along the view. Without a matrix there is no heading to be
    had, and anything told none chooses by distance alone.
    """
    if view_projection is None:
        return None
    import numpy as np
    matrix = np.asarray(view_projection, dtype='d')
    if matrix.shape != (4, 4):                   # pragma: no cover - defensive
        return None
    forward = matrix[3, :3] + matrix[2, :3]
    length = float(np.linalg.norm(forward))
    return None if length < 1e-9 else forward / length


def _beside(base_uri: str, name: str, cache_dir: Optional[str]) -> Any:
    """A file named from a tileset, as something an image decoder can open.

    Local worlds are the common case and resolve to a path; a remote one comes
    back as its bytes, which is the other thing PIL accepts.
    """
    uri = base_uri + name if fetch.is_url(base_uri) else os.path.join(base_uri, name)
    if not fetch.is_url(uri):
        return uri
    return io.BytesIO(fetch.read_bytes(uri, cache_dir=cache_dir))
