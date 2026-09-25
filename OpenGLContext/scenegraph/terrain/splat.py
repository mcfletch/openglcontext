"""A landscape drawn from its height field: :class:`SplatTerrain`.

A :class:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField` meshed
whole and drawn as ground: up to four detail materials blended per pixel by an
RGBA control map, with a baked sun-shadow and tree-canopy term for its static
shading. The drawing is :class:`~OpenGLContext.scenegraph.terrain.ground.GroundShading`
and :class:`~OpenGLContext.scenegraph.terrain.ground.GroundPatch`, the same
ground a streamed world's tiles are drawn with; this node works out the light
baked into the landscape, and where cover and trees stand in it.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from vrml.vrml97 import basenodes as vnodes

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.terrain.ground import DEFAULT_SUN, GroundPatch, GroundShading

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

#: How dark it is under a canopy. ``CANOPY_SHADE`` is how hard a closed canopy
#: darkens the light and ``CANOPY_DEEPEST`` the most of it that may go, so what
#: is left where the canopy opens is the sun breaking through. A forest floor is
#: dark and the open ground beside it is not.
#:
#: ``CANOPY_CROWN`` is how wide a tree's crown is, in metres, which is the ground
#: one tree shades: a stand is closed when its crowns meet, not when its trunks
#: do. ``CANOPY_SPREAD`` offsets the shadow along the light, away from the sun,
#: because a tree casts its shadow along the light rather than straight down.
CANOPY_SHADE = 1.3
CANOPY_DEEPEST = 0.78
CANOPY_CROWN = 7.0
CANOPY_SPREAD = 12.0


class SplatTerrain(vnodes.PointSet):
    """Splat-textured terrain over a :class:`HeightField`.

    Subclasses ``PointSet`` only to inherit the scenegraph render hook; it draws
    the field's mesh as a :class:`GroundPatch`, not points.

    :param height_field: the :class:`HeightField` to render and shade.
    :param layers: up to four material names, blended by the control map's RGBA.
    :param control: the RGBA splat control map -- a path, an open image, or the
        bytes of one.
    :param material_fn: ``material_fn(name, res)`` resolving a layer's texture paths;
        defaults to the cc0/ambientCG material fetcher.
    :param canopy: optional (N, 3) trunk positions; when set the baked shadow is
        darkened under tree cover for dappled shade. Set before first render.
    :param canopy_shade: how hard the canopy darkens what is under it, and
        :param canopy_deepest: the most it may, as a fraction of the light. A
        forest floor is *dark*; the light default reads as an orchard. What is
        left where the density is low is the sun breaking through.
    :param canopy_crown: how wide a tree's crown is in metres, which is the
        ground one tree shades.
    :param canopy_spread: how far the canopy's shadow is offset along the
        light, away from the sun, in metres -- trees cast along the light, not
        straight down.
    :param sun: which way the sunlight travels, pointing down from the sun
        (:data:`~OpenGLContext.scenegraph.terrain.ground.DEFAULT_SUN`).
    :param holes: ``holes(x, z) -> mask``, true where the ground is not there --
        over a tunnel's bore, say. Hand the *same* callable to
        :class:`~OpenGLContext.physics.heightfield.HeightFieldColliders` and the
        surface drawn and the surface collided against are the same surface; see
        :meth:`~OpenGLContext.scenegraph.terrain.HeightField.mesh`. It may be set
        at any time: the mesh is cut again at the next draw.
    """
    #: One draw serves every view that sees the terrain; see GroundPatch.
    multiviewShared = True
    #: Whether the terrain draws and casts, the application's switch; see
    #: :class:`~OpenGLContext.scenegraph.instancedgl.GLLayer`.
    drawn: bool = True

    def __init__(self, height_field: "HeightField", layers: "list[str]", control: Any,
                 sun: "tuple[float, float, float]" = DEFAULT_SUN,
                 material_fn: "Optional[Callable[..., dict[str, Any]]]" = None,
                 canopy: Optional[np.ndarray] = None,
                 canopy_shade: float = CANOPY_SHADE,
                 canopy_deepest: float = CANOPY_DEEPEST,
                 canopy_crown: float = CANOPY_CROWN,
                 canopy_spread: float = CANOPY_SPREAD,
                 holes: "Optional[Callable[[Any, Any], Any]]" = None) -> None:
        super(SplatTerrain, self).__init__()
        self.hf = height_field
        self._patch: Any = None
        #: Meshes a new :attr:`holes` replaced, released at the next draw.
        self._replaced: "list[GroundPatch]" = []
        self.holes = holes
        self.layers = layers
        self.control = control
        if material_fn is None:
            from OpenGLContext.loaders import cc0
            material_fn = cc0.material
        self.material_fn = material_fn
        self.sun = np.asarray(sun, 'd')
        self.sun /= np.linalg.norm(self.sun)
        self.canopy = canopy
        self.canopy_shade = float(canopy_shade)
        self.canopy_deepest = float(canopy_deepest)
        self.canopy_crown = float(canopy_crown)
        self.canopy_spread = float(canopy_spread)
        self._shading: Any = None
        self._closure: Any = None
        self._ground: Any = None

    @property
    def shading(self) -> np.ndarray:
        """How much of the sun reaches each cell of the ground, in [0, 1].

        The hillside's own shadow with the canopy's over it, on the height
        field's grid. It is what the terrain is drawn with, and it is public
        because everything else standing on this ground has to agree with it:
        grass lit like an open field under a closed canopy is a lamp on the
        forest floor. See :meth:`shade`.
        """
        if self._shading is None:
            lit = self.hf.sun_shadow(self.sun)
            if self.canopy is not None and len(self.canopy):
                lit = self.hf.canopy_shadow(lit, self.canopy, self.sun,
                                            spread=self.canopy_spread,
                                            crown=self.canopy_crown,
                                            darken=self.canopy_shade,
                                            cap=self.canopy_deepest)
            self._shading = np.asarray(lit)
        shading: np.ndarray = self._shading
        return shading

    def shade(self, x: Any, z: Any) -> Any:
        """How much of the sun reaches these world positions, in [0, 1].

        Arrays in, array out, for a caller placing a great many things at once.
        """
        return self._sampled(self.shading, x, z)

    @property
    def closure(self) -> np.ndarray:
        """How closed the canopy is over each cell: 0 open, 1 a crown deep.

        Unclamped, unlike :attr:`shading`, which is what makes it the thing to
        place plants by: past a certain density more trees take no more light,
        so a stand with gaps in it and a closed one shade the floor alike. They
        are not alike to stand in -- one has room for shrubs and the other does
        not. See
        :meth:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField.canopy_density`.
        """
        if self._closure is None:
            resolution = self.shading.shape[0]
            self._closure = (
                np.zeros((resolution, resolution), np.float32)
                if self.canopy is None or not len(self.canopy)
                else self.hf.canopy_density(self.canopy, resolution,
                                            crown=self.canopy_crown))
        closure: np.ndarray = self._closure
        return closure

    def canopy_cover(self, x: Any, z: Any) -> Any:
        """How closed the canopy is over these world positions.

        Arrays in, array out, like :meth:`shade`, and read the same way -- a
        caller placing a great many plants asks once for all of them.
        """
        return self._sampled(self.closure, x, z)

    def _sampled(self, grid: np.ndarray, x: Any, z: Any) -> Any:
        """A grid over this terrain's extent, read at world positions."""
        size = grid.shape[0]
        extent = self.hf.extent
        u = np.clip((np.asarray(x, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        v = np.clip((np.asarray(z, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        return np.asarray(grid[v, u])

    @property
    def ground(self) -> GroundShading:
        """What this terrain is made of, as a world's ground shading.

        The layers, the control map and the light baked into the landscape, held
        apart from the mesh they are drawn on so a streamed world's tiles can be
        drawn with the same ground (:mod:`OpenGLContext.scenegraph.terrain.ground`).
        """
        if self._ground is None:
            self._ground = GroundShading(
                extent=self.hf.extent, layers=self.layers, control=self.control,
                shading=self.shading, sun=self.sun,
                material_fn=self.material_fn)
        found: GroundShading = self._ground
        return found

    @property
    def holes(self) -> "Optional[Callable[[Any, Any], Any]]":
        """Where the ground is not there: ``holes(x, z) -> mask``, or None.

        Setting it drops the mesh, which is cut again with it at the next draw;
        the GL objects of the one it replaces are released then, on the GL
        thread.
        """
        return self.__dict__.get('_holes')

    @holes.setter
    def holes(self, holes: "Optional[Callable[[Any, Any], Any]]") -> None:
        self.__dict__['_holes'] = holes
        if self._patch is not None:
            self._replaced.append(self._patch)
            self._patch = None

    def _release_replaced(self) -> None:
        """Release the meshes a new :attr:`holes` replaced. GL thread."""
        replaced, self._replaced = self._replaced, []
        for patch in replaced:
            patch.dispose()

    @property
    def patch(self) -> GroundPatch:
        """The field's own mesh, drawn with that ground.

        Built at the first draw rather than at construction, because what it is
        cut by is not settled until then: a game reads a tileset to stand the
        ground up and reads it again to find the roads, and only the roads know
        where a bore runs (:attr:`holes`). Built again after :attr:`holes`
        changes.
        """
        if self._patch is None:
            vertices, indices = self.hf.mesh(holes=self.holes)
            self._patch = GroundPatch(self.ground, vertices, indices)
        found: GroundPatch = self._patch
        return found

    def render_depth(self, mode: Any) -> int:
        """Write the ground's depth for a shadow map."""
        self._release_replaced()
        if not self.drawn:
            return 1
        return self.patch.render_depth(mode)

    def dispose(self) -> None:
        """Free this node's GL objects (mesh, textures, program). GL thread."""
        self._release_replaced()
        if self._patch is not None:
            self._patch.dispose()
            self._patch = None
        if self._ground is not None:
            self._ground.dispose()
            self._ground = None

    def boundingVolume(self, mode: Any) -> "boundingvolume.AABoundingBox":
        E = self.hf.extent
        H = self.hf.relief * 3
        return boundingvolume.AABoundingBox(
            size=(E, H, E), center=(0, self.hf.base + self.hf.relief / 2.0, 0))

    def render(self, mode: Any = None, **kw: Any) -> int:
        self._release_replaced()
        if not self.drawn:
            return 1
        return self.patch.render(mode, **kw)
