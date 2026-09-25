"""The arithmetic of planar reflections: which surfaces mirror the scene, and how.

A surface is a mirror when its material carries a
:class:`~OpenGLContext.scenegraph.reflector.PlanarReflector`
(:func:`reflector_for`), and water is one whatever its material. Its plane is
the best fit through its mesh (:func:`fit_plane`), carried into the world by
its placement (:func:`surface_plane`); a mesh that is not flat reflects the
probe instead, since a planar reflection of a curved surface is right along
one line only.

What a mirror reflects is the scene seen through another camera: the view
mirrored in its plane (:func:`mirror_matrix`), with a projection cropped to the
mirror's part of the screen (:func:`screen_rect`, :func:`crop_matrix`) and a
near plane lying on the mirror (:func:`oblique_projection`), which clips what
stands behind it in every program the pass draws with. :func:`plan_mirror`
puts those together into a :class:`MirrorView`, which is an ordinary view to
the multi-view machinery: its matrices go into a
:class:`~OpenGLContext.multiview.strategy.ViewFrame` unchanged.

A fragment of the mirror reads its reflection by projecting its world position
through the matrix the reflection was drawn with (:func:`atlas_lookup` is that
arithmetic, as the shader does it), so a reflection drawn a frame or two ago is
still read in the right place.

Everything here is plain arithmetic with no GL. Matrices are row-vector, as the
engine's are: ``point @ matrix``. The pass that draws the reflections is
:meth:`~OpenGLContext.passes.flateffects._FlatEffectsMixin.renderReflections`,
and what it draws into is :mod:`OpenGLContext.passes.reflectionatlas`.
"""
from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from numpy.typing import ArrayLike

from OpenGLContext.scenegraph.reflector import WATER, WATER_DISTORTION, PlanarReflector

log = logging.getLogger(__name__)

__all__ = [
    'REFLECTION_UNIT', 'REFLECTION_UNITS_NEEDED', 'FLATNESS', 'GUARD',
    'ROUGHEST', 'WATER_REFLECTOR', 'Plane', 'MeshPlane', 'NDCRect', 'WHOLE',
    'TEXEL_STEP', 'TileRect', 'MirrorView', 'shape_material', 'shape_reflector',
    'reflector_for', 'surface_roughness', 'is_reflector',
    'is_water', 'mirror_generation', 'fit_plane', 'fan', 'mesh_plane',
    'surface_plane', 'local_plane', 'place_plane', 'world_corners',
    'box_corners', 'guarded', 'contains', 'tile_bounds', 'mirror_matrix', 'eye_plane',
    'oblique_projection', 'screen_rect', 'crop_matrix', 'texels', 'plan_mirror',
    'tile_transform', 'atlas_lookup', 'fov', 'too_small', 'SMALLEST',
]

#: The texture unit reflections are read from: past the joint palette (30),
#: so it exists only on a driver whose fragment stage has more units than that.
REFLECTION_UNIT = 31

#: How many fragment texture units a driver needs for reflections to be
#: compiled in at all.
REFLECTION_UNITS_NEEDED = REFLECTION_UNIT + 1

#: How far a mesh's points may stand off its best-fit plane, as a share of the
#: mesh's extent, and still be a mirror.
FLATNESS = 0.01

#: The guard band round a mirror's rectangle, as a share of the rectangle each
#: side: a turn of the head between redraws stays inside what was drawn.
GUARD = 0.1

#: Above this roughness a reflector is not drawn: the prefiltered probe is as
#: blurred as that reflection would be.
ROUGHEST = 0.6

#: The reflector a body of water is, where its material names none.
WATER_REFLECTOR = WATER

#: A plane in the world: a point on it and its unit normal, which points to
#: the side the mirror is seen from.
Plane = Tuple[np.ndarray, np.ndarray]


# --- which surfaces are mirrors -----------------------------------------------

def is_water(record: Any) -> bool:
    """Whether a draw record is a body of water: its geometry has a wave."""
    return bool(getattr(getattr(record[5], 'geometry', None), 'waveStyle', None))


def shape_material(shape: Any) -> Any:
    """The material a shape is drawn with: its appearance's, else its mesh's own."""
    material = getattr(getattr(shape, 'appearance', None), 'material', None)
    if material is None:
        material = getattr(getattr(shape, 'geometry', None), 'material', None)
    return material


def shape_reflector(shape: Any) -> Optional[PlanarReflector]:
    """The reflector a shape's surface mirrors the scene by, or None.

    The material's own where it carries one, :data:`WATER_REFLECTOR` for water
    whose material names none, and None for everything else -- and for a
    reflector switched off, which leaves the surface reflecting the probe.
    """
    geometry = getattr(shape, 'geometry', None)
    reflector = getattr(shape_material(shape), 'reflector', None)
    if reflector:
        return reflector if reflector.enabled else None
    if getattr(geometry, 'waveStyle', None):
        return WATER_REFLECTOR
    return None


def reflector_for(record: Any) -> Optional[PlanarReflector]:
    """The reflector a draw record's surface mirrors the scene by, or None."""
    return shape_reflector(record[5])


def surface_roughness(material: Any) -> float:
    """How rough a material's surface is on average: its factor times its map.

    A glTF material commonly carries a factor of 1 and the roughness itself in
    the green channel of its metallic-roughness map, so the factor alone says
    nothing about how sharp a reflection it gives. The map's mean is the
    texture's :meth:`~OpenGLContext.scenegraph.pbrmaterial.PBRTexture.mean_roughness`.
    """
    factor = float(getattr(material, 'roughness', 0.0) or 0.0)
    textures = getattr(material, 'textures', None) or {}
    texture = textures.get('metallicRoughness')
    if texture is None or getattr(texture, 'image', None) is None:
        return factor
    return factor * float(texture.mean_roughness())


def is_reflector(record: Any) -> bool:
    """Whether a draw record's surface mirrors the scene."""
    return reflector_for(record) is not None


_mirror_changes = 0


def mirror_generation() -> int:
    """A count that moves whenever a field deciding which shapes are mirrors is set.

    Those are a shape's ``appearance`` and ``geometry``, an appearance's
    ``material``, a material's ``reflector``, a reflector's ``enabled`` and a
    mesh's ``waveStyle``, which makes it water. A
    pass that remembers which of the scene's shapes are mirrors keeps the
    answer while this and its set of paths stay as they were.
    """
    return _mirror_changes


def _mirrors_changed(*_args: Any, **_named: Any) -> None:
    global _mirror_changes
    _mirror_changes += 1


def _watch_mirror_fields() -> None:
    from pydispatch import dispatcher
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.shape import Shape
    for owner, name in ((Shape, 'appearance'), (Shape, 'geometry'),
                        (Appearance, 'material'), (PBRMaterial, 'reflector'),
                        (PlanarReflector, 'enabled'), (PBRMesh, 'waveStyle')):
        dispatcher.connect(_mirrors_changed, signal=('set', getattr(owner, name)),
                           weak=False)


_watch_mirror_fields()


# --- the plane of a mesh ------------------------------------------------------

class MeshPlane(NamedTuple):
    """A mesh's best-fit plane in its own space.

    ``point`` is the mean of its points and ``normal`` the direction they vary
    least in, turned to the side its triangles face. ``flat`` says whether
    every point is within :data:`FLATNESS` of the plane; ``corners`` are the
    mesh's bounding box, which is what its rectangle on screen is found from.
    """

    point: np.ndarray
    normal: np.ndarray
    flat: bool
    corners: np.ndarray


def box_corners(points: ArrayLike) -> np.ndarray:
    """The eight corners of the box round ``points``."""
    points = np.asarray(points, 'd').reshape(-1, 3)
    low, high = points.min(axis=0), points.max(axis=0)
    return np.array([(x, y, z) for x in (low[0], high[0])
                     for y in (low[1], high[1]) for z in (low[2], high[2])])


def _facing(points: np.ndarray, indices: Optional[np.ndarray]) -> np.ndarray:
    """The area-weighted direction the triangles face, by their winding."""
    if indices is None or len(indices) < 3:
        count = len(points) - len(points) % 3
        if count < 3:
            return np.zeros(3)
        triangles = points[:count].reshape(-1, 3, 3)
    else:
        corners = np.asarray(indices, 'i8').reshape(-1)
        corners = corners[:len(corners) - len(corners) % 3]
        triangles = points[corners].reshape(-1, 3, 3)
    return np.cross(triangles[:, 1] - triangles[:, 0],
                    triangles[:, 2] - triangles[:, 0]).sum(axis=0)


def fit_plane(positions: ArrayLike, indices: Optional[ArrayLike] = None) -> Optional[MeshPlane]:
    """The best-fit plane through a mesh's points, or None for fewer than three.

    ``indices`` are its triangles, three to a face, whose winding decides
    which way the normal faces; without them the points are read as
    triangles in order.
    """
    points = np.asarray(positions, 'd').reshape(-1, 3)
    if len(points) < 3:
        return None
    centre = points.mean(axis=0)
    offsets = points - centre
    _u, _s, axes = np.linalg.svd(offsets, full_matrices=False)
    normal = axes[-1]
    facing = _facing(points, None if indices is None else np.asarray(indices))
    if float(np.dot(facing, normal)) < 0.0:
        normal = -normal
    extent = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    worst = float(np.abs(offsets @ normal).max())
    flat = extent > 0.0 and worst <= FLATNESS * extent
    return MeshPlane(centre, normal, flat, box_corners(points))


class _Fit(NamedTuple):
    """A geometry's plane, and the inputs it was worked out from.

    The arrays are held, not their ``id()``, so an array released and a new
    one given its address is never taken for the one fitted.
    """

    water: bool
    positions: Any
    indices: Any
    ccw: bool
    plane: Optional[MeshPlane]

    def serves(self, water: bool, positions: Any, indices: Any, ccw: bool) -> bool:
        """Whether this fit is the one those inputs give."""
        return (self.water == water and self.positions is positions
                and self.indices is indices and self.ccw == ccw)


#: Each geometry's plane, kept while the geometry lives and worked out again
#: when its point array, its index array, its ``ccw`` or its being water
#: changes. An array edited in place is not seen; a geometry whose points move
#: is given a new array, as a deformed mesh is.
_FITS: "weakref.WeakKeyDictionary[Any, _Fit]" = weakref.WeakKeyDictionary()


def _geometry_points(geometry: Any) -> Tuple[Any, Any, bool]:
    """A geometry's vertex positions, what its faces are indexed by, and
    whether those are polygons.

    ``positions`` and its triangles' ``indices`` for a mesh, ``coord.point``
    and the ``coordIndex`` polygons for an ``IndexedFaceSet``, and
    ``(None, None, False)`` for neither.
    """
    positions = getattr(geometry, 'positions', None)
    if positions is not None and len(positions):
        indices = getattr(geometry, 'indices', None)
        return positions, (indices if indices is not None and len(indices) else None), False
    coord = getattr(geometry, 'coord', None)
    points = getattr(coord, 'point', None)
    if points is None or not len(points):
        return None, None, False
    return points, getattr(geometry, 'coordIndex', None), True


def fan(polygons: Any) -> Optional[np.ndarray]:
    """``coordIndex`` polygons, each fanned into triangles, or None for none.

    Polygons are separated by -1; the last needs no -1 after it, and one of
    fewer than three corners makes no triangle.
    """
    indices = np.asarray(polygons if polygons is not None else (), 'i8').reshape(-1)
    if not len(indices):
        return None
    ends = np.flatnonzero(indices < 0)
    starts = np.r_[0, ends + 1]
    stops = np.r_[ends, len(indices)]
    corners = stops - starts
    counts = np.maximum(corners - 2, 0)
    if not counts.sum():
        return None
    # Each triangle is (first, first + k, first + k + 1) of its polygon.
    first = np.repeat(starts, counts)
    step = np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts) + 1
    return np.stack([indices[first], indices[first + step],
                     indices[first + step + 1]], axis=1).reshape(-1)


def _fit(geometry: Any, water: bool) -> Optional[MeshPlane]:
    """A geometry's plane in its own space, from its fit if it has one."""
    positions, indices, polygons = _geometry_points(geometry)
    if positions is None:
        return None
    ccw = bool(getattr(geometry, 'ccw', True))
    try:
        known = _FITS.get(geometry)
    except TypeError:                      # pragma: no cover - not weakly referable
        known = None
    if known is not None and known.serves(water, positions, indices, ccw):
        return known.plane
    if water:
        fitted = _water_plane(positions)
    else:
        fitted = fit_plane(positions, fan(indices) if polygons else indices)
        if fitted is not None and not ccw:
            fitted = fitted._replace(normal=-fitted.normal)
        if fitted is not None and not fitted.flat:
            log.warning('%s is marked as a mirror and is not flat; it reflects '
                        'the environment probe', type(geometry).__name__)
    try:
        _FITS[geometry] = _Fit(water, positions, indices, ccw, fitted)
    except TypeError:                      # pragma: no cover - not weakly referable
        pass
    return fitted


def mesh_plane(geometry: Any) -> Optional[MeshPlane]:
    """A geometry's plane in its own space, fitted once and kept.

    None where the geometry has no points or is not flat; a mesh that is not
    flat is reported once, when it is first asked about. The normal faces the
    side the faces' winding makes the front, which ``ccw`` False turns over.
    """
    fitted = _fit(geometry, water=False)
    if fitted is None or not fitted.flat:
        return None
    return fitted


def _water_plane(positions: Any) -> Optional[MeshPlane]:
    """A water sheet's plane in its own space: its mean level, facing up.

    A sheet is meshed flat in its own x and z and its wave is a displacement
    of that, so its plane is found from its level rather than fitted to
    points the wave may already have moved.
    """
    points = np.asarray(positions, 'd').reshape(-1, 3)
    if not len(points):
        return None
    level = float(points[:, 1].mean())
    return MeshPlane(np.array([0.0, level, 0.0]), np.array([0.0, 1.0, 0.0]),
                     True, box_corners(points))


def local_plane(record: Any) -> Optional[MeshPlane]:
    """A draw record's mirror plane in its geometry's own space, or None."""
    geometry = getattr(record[5], 'geometry', None)
    if geometry is None:
        return None
    if is_water(record):
        return _fit(geometry, water=True)
    return mesh_plane(geometry)


def place_plane(fitted: MeshPlane, tmatrix: Any) -> Optional[Plane]:
    """A plane in a geometry's own space, carried into the world by ``tmatrix``.

    The normal goes through the inverse of the placement's linear part, which
    keeps it perpendicular to the surface under any scale or shear.
    """
    placement = np.asarray(tmatrix, 'd')
    point = np.append(fitted.point, 1.0) @ placement
    try:
        normal = np.linalg.solve(placement[:3, :3], fitted.normal)
    except np.linalg.LinAlgError:
        return None
    length = float(np.linalg.norm(normal))
    if length == 0.0 or point[3] == 0.0:
        return None
    return point[:3] / point[3], normal / length


def surface_plane(record: Any) -> Optional[Plane]:
    """The world plane a draw record's surface mirrors in, or None."""
    fitted = local_plane(record)
    if fitted is None:
        return None
    return place_plane(fitted, record[2])


def world_corners(fitted: MeshPlane, tmatrix: Any) -> np.ndarray:
    """A mesh's bounding box corners, placed in the world by ``tmatrix``."""
    placed = np.c_[fitted.corners, np.ones(len(fitted.corners))] @ np.asarray(tmatrix, 'd')
    return np.asarray(placed[:, :3] / placed[:, 3:])


# --- the mirrored camera ------------------------------------------------------

def mirror_matrix(point: ArrayLike, normal: ArrayLike) -> np.ndarray:
    """The world reflected in the plane through ``point`` facing ``normal``."""
    n = np.asarray(normal, dtype='d')[:3]
    n = n / np.linalg.norm(n)
    distance = float(np.dot(n, np.asarray(point, dtype='d')[:3]))
    mirror = np.identity(4)
    mirror[:3, :3] -= 2.0 * np.outer(n, n)
    mirror[3, :3] = 2.0 * distance * n
    return mirror


def eye_plane(point: ArrayLike, normal: ArrayLike, view: Any) -> np.ndarray:
    """A world plane in the eye space ``view`` takes the world to.

    Returned as the four coefficients ``(a, b, c, d)`` whose dot product with
    an eye-space point ``(x, y, z, 1)`` is positive on the side ``normal``
    faces.
    """
    n = np.asarray(normal, dtype='d')[:3]
    world = np.append(n, -float(np.dot(n, np.asarray(point, dtype='d')[:3])))
    return np.asarray(np.linalg.inv(np.asarray(view, dtype='d')) @ world, dtype='d')


def oblique_projection(projection: Any, plane: ArrayLike) -> np.ndarray:
    """``projection`` with its near plane moved onto ``plane``, in eye space.

    What is on the negative side of the plane is clipped by the near plane,
    in every shader, with nothing in any shader to do it; where a kept point
    lands on screen is unchanged, and only depth is bent. The camera has to
    stand on the negative side, as a camera mirrored behind a mirror does.
    This is Lengyel's oblique near-plane clipping, which holds for an
    off-centre projection as for a centred one.
    """
    column = np.array(projection, dtype='d').T
    clip = np.asarray(plane, dtype='d')
    corner = np.linalg.inv(column) @ np.array(
        [np.sign(clip[0]), np.sign(clip[1]), 1.0, 1.0])
    scaled = clip * (2.0 / float(np.dot(clip, corner)))
    column[2] = scaled - column[3]
    return column.T


# --- the part of the screen a mirror covers -----------------------------------

#: A rectangle in normalised device coordinates: ``(x0, y0, x1, y1)``.
NDCRect = Tuple[float, float, float, float]

#: The whole view, in normalised device coordinates.
WHOLE: NDCRect = (-1.0, -1.0, 1.0, 1.0)


def screen_rect(corners: ArrayLike, modelproj: Any) -> Optional[NDCRect]:
    """Where world ``corners`` -- a box's, or several boxes' -- fall in a view,
    clipped to it, or None.

    None where the box is wholly off screen or behind the camera. A box the
    camera's plane cuts through covers an unbounded part of the view, and is
    given the whole of it.
    """
    points = np.asarray(corners, 'd').reshape(-1, 3)
    points = np.c_[points, np.ones(len(points))]
    clip = points @ np.asarray(modelproj, 'd')
    w = clip[:, 3]
    if (w <= 1e-6).all():
        return None
    if (w <= 1e-6).any():
        return WHOLE
    ndc = clip[:, :2] / w[:, None]
    low, high = ndc.min(axis=0), ndc.max(axis=0)
    x0, y0 = max(float(low[0]), -1.0), max(float(low[1]), -1.0)
    x1, y1 = min(float(high[0]), 1.0), min(float(high[1]), 1.0)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def guarded(rect: NDCRect, guard: float = GUARD) -> NDCRect:
    """``rect`` grown by ``guard`` of its size on every side."""
    x0, y0, x1, y1 = rect
    dx, dy = (x1 - x0) * guard, (y1 - y0) * guard
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def contains(outer: NDCRect, inner: NDCRect) -> bool:
    """Whether ``inner`` lies wholly within ``outer``."""
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def crop_matrix(rect: NDCRect) -> np.ndarray:
    """What takes ``rect`` of a view to the whole of a viewport, in clip space."""
    x0, y0, x1, y1 = rect
    sx, sy = 2.0 / (x1 - x0), 2.0 / (y1 - y0)
    crop = np.identity(4)
    crop[0, 0], crop[1, 1] = sx, sy
    crop[3, 0] = -sx * (x0 + x1) / 2.0
    crop[3, 1] = -sy * (y0 + y1) / 2.0
    return crop


#: Tile sizes are rounded up to a multiple of this many texels, so a mirror
#: whose rectangle changes by a pixel keeps its tile.
TEXEL_STEP = 8


def texels(extent: float) -> int:
    """``extent`` texels rounded up to a whole :data:`TEXEL_STEP`, at least one step."""
    return max(TEXEL_STEP, int(np.ceil(extent / TEXEL_STEP)) * TEXEL_STEP)


@dataclass(frozen=True)
class MirrorView:
    """One mirror seen from one view: the camera its reflection is drawn through.

    ``modelView`` is the view's camera mirrored in the plane, and
    ``projection`` the view's, cropped to ``crop`` -- the mirror's rectangle
    and its guard band, in the view's normalised device coordinates -- with its
    near plane on the mirror. ``lookup`` is world to the mirrored camera's clip
    space *before* the crop, which is what a fragment of the mirror projects
    itself through; ``size`` is the tile the reflection is drawn into, in
    texels. ``rect`` is the mirror's own rectangle, without the guard band.
    """

    point: np.ndarray
    normal: np.ndarray
    modelView: np.ndarray
    projection: np.ndarray
    lookup: np.ndarray
    crop: NDCRect
    rect: NDCRect
    size: Tuple[int, int]

    @property
    def modelproj(self) -> np.ndarray:
        """World to the tile's clip space, through the mirror."""
        return np.asarray(self.modelView @ self.projection, dtype='d')


def plan_mirror(plane: Optional[Plane], corners: ArrayLike, view: Any,
                projection: Any, view_rect: Sequence[int], scale: float,
                crop: Optional[NDCRect] = None,
                eye: Optional[ArrayLike] = None) -> Optional[MirrorView]:
    """The view of one mirror from one camera, or None where it shows nothing.

    ``corners`` are the mirror's bounding box in the world and ``view_rect``
    the view's rectangle in window pixels, which with ``scale`` sizes the
    tile. None where the camera stands behind the mirror or the mirror is off
    screen. ``crop`` keeps a crop the caller already has a tile for, where it
    still holds the mirror. ``eye`` is where the camera stands in the world,
    worked out from ``view`` where not given.
    """
    if plane is None:
        return None
    point, normal = plane
    view = np.asarray(view, 'd')
    projection = np.asarray(projection, 'd')
    eye = np.linalg.inv(view)[3, :3] if eye is None else np.asarray(eye, 'd')[:3]
    if float(np.dot(eye - point, normal)) <= 0.0:
        return None
    rect = screen_rect(corners, view @ projection)
    if rect is None:
        return None
    if crop is None or not contains(crop, rect):
        crop = guarded(rect)
    mirrored = mirror_matrix(point, normal) @ view
    cropped = projection @ crop_matrix(crop)
    clipped = oblique_projection(cropped, eye_plane(point, normal, mirrored))
    width = (crop[2] - crop[0]) / 2.0 * float(view_rect[2]) * scale
    height = (crop[3] - crop[1]) / 2.0 * float(view_rect[3]) * scale
    return MirrorView(point, normal, mirrored, clipped, mirrored @ projection,
                      crop, rect, (texels(width), texels(height)))


def fov(projection: Any) -> float:
    """A projection's vertical field of view, in radians."""
    focal = float(np.asarray(projection, 'd')[1, 1])
    return 2.0 * float(np.arctan(1.0 / focal)) if focal > 0.0 else float(np.pi / 2.0)


#: A shape whose bounds cover fewer texels of a tile than this is left out of
#: that mirror's view.
SMALLEST = 2.0


def too_small(record: Any, eye: ArrayLike, texels_per_radian: float) -> bool:
    """Whether a draw record would cover under :data:`SMALLEST` texels.

    Measured from its bounding box's size and centre as the camera at ``eye``
    sees them; a record with no box of its own is never too small.
    """
    volume = record[3]
    size = getattr(volume, 'size', None)
    centre = getattr(volume, 'center', None)
    if size is None or centre is None:
        return False
    placement = np.asarray(record[2], 'd')
    scale = float(np.linalg.norm(placement[:3, :3], axis=1).max())
    radius = 0.5 * float(np.linalg.norm(np.asarray(size, 'd'))) * scale
    middle = np.append(np.asarray(centre, 'd')[:3], 1.0) @ placement
    distance = float(np.linalg.norm(middle[:3] / middle[3] - np.asarray(eye, 'd')[:3]))
    if distance <= radius:
        return False
    return bool(2.0 * np.arctan(radius / distance) * texels_per_radian < SMALLEST)


# --- reading a reflection -----------------------------------------------------

#: A tile's place in the atlas, in texels: ``(x, y, width, height)``.
TileRect = Tuple[int, int, int, int]


def tile_transform(crop: NDCRect, tile: TileRect,
                   atlas: Tuple[int, int]) -> Tuple[float, float, float, float]:
    """What takes a normalised device position in a mirror's view to the atlas.

    ``(scale_x, scale_y, offset_x, offset_y)``: the atlas coordinate is
    ``ndc * scale + offset``, which is the ``planarTile`` uniform.
    """
    x0, y0, x1, y1 = crop
    sx = tile[2] / (atlas[0] * (x1 - x0))
    sy = tile[3] / (atlas[1] * (y1 - y0))
    return (sx, sy, tile[0] / atlas[0] - x0 * sx, tile[1] / atlas[1] - y0 * sy)


def tile_bounds(tile: TileRect, atlas: Tuple[int, int]) -> Tuple[float, float, float, float]:
    """A tile's texels in atlas coordinates, half a texel in from each edge.

    ``(u0, v0, u1, v1)``, which is the ``planarBounds`` uniform: a lookup is
    clamped inside it, so filtering never reaches a neighbour's texels.
    """
    return ((tile[0] + 0.5) / atlas[0], (tile[1] + 0.5) / atlas[1],
            (tile[0] + tile[2] - 0.5) / atlas[0], (tile[1] + tile[3] - 0.5) / atlas[1])


def atlas_lookup(world: ArrayLike, mirror: MirrorView, tile: TileRect,
                 atlas: Tuple[int, int]) -> Tuple[float, float]:
    """Where a point on the mirror reads its reflection, in atlas coordinates.

    The shader's arithmetic, with no distortion: the point through the tile's
    ``lookup`` matrix, and the result into the tile.
    """
    clip = np.append(np.asarray(world, 'd')[:3], 1.0) @ mirror.lookup
    ndc = clip[:2] / clip[3]
    sx, sy, ox, oy = tile_transform(mirror.crop, tile, atlas)
    return float(ndc[0] * sx + ox), float(ndc[1] * sy + oy)
