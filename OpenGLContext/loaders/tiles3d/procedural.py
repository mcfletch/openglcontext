"""Procedural terrain with real-world-like features, baked to a 3D Tiles quadtree.

Generates a signed height field combining broad rolling hills, ridged mountains, a
carved river canyon, and a lake basin, with per-vertex colours (grass, rock, snow,
water) so the terrain reads as a landscape rather than flat-shaded noise. The same
continuous height field is sampled per tile at the tile's resolution, so a quadtree
of tiles forms a coherent multi-resolution surface for the streaming runtime to page.

Vectorised value-noise fBm (numpy only, deterministic) — no external noise library.
"""
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

HeightFn = Callable[[np.ndarray, np.ndarray], np.ndarray]
#: Per-vertex colour from a patch's positions and normals -- (N,3)/(N,3) in,
#: (N,3) float RGB out.
ColorFn = Callable[[np.ndarray, np.ndarray], np.ndarray]

WATER_LEVEL = 0.0


# --- deterministic value-noise fBm --------------------------------------------

def _hash01(ix: np.ndarray, iz: np.ndarray, seed: int) -> np.ndarray:
    h = (ix.astype(np.int64) * 374761393 + iz.astype(np.int64) * 668265263
         + np.int64(seed) * 1013904223)
    h = (h ^ (h >> np.int64(13))) * np.int64(1274126177)
    h = h ^ (h >> np.int64(16))
    return (h & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def _value_noise(x: np.ndarray, z: np.ndarray, seed: int) -> np.ndarray:
    x0 = np.floor(x).astype(np.int64)
    z0 = np.floor(z).astype(np.int64)
    fx = _smooth(x - x0)
    fz = _smooth(z - z0)
    v00 = _hash01(x0, z0, seed)
    v10 = _hash01(x0 + 1, z0, seed)
    v01 = _hash01(x0, z0 + 1, seed)
    v11 = _hash01(x0 + 1, z0 + 1, seed)
    top = v00 * (1 - fx) + v10 * fx
    bot = v01 * (1 - fx) + v11 * fx
    return top * (1 - fz) + bot * fz


def _fbm(
    x: np.ndarray,
    z: np.ndarray,
    seed: int,
    octaves: int = 5,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> np.ndarray:
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * _value_noise(x * freq, z * freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def _ridged(x: np.ndarray, z: np.ndarray, seed: int, octaves: int = 5) -> np.ndarray:
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = _value_noise(x * freq, z * freq, seed + o * 211)
        r = 1.0 - np.abs(2.0 * n - 1.0)
        total += amp * (r * r)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def fbm(x: np.ndarray, z: np.ndarray, seed: int = 0, octaves: int = 5,
        lacunarity: float = 2.0, gain: float = 0.5) -> np.ndarray:
    """Fractal value noise over ``(x, z)``, from 0 to 1.

    Deterministic in ``seed``, vectorised, and numpy-only. This is the grain
    the shipped landscape is made of, so anything that wants to add to it --
    a sculpted hill, a scatter mask, a splat weight -- can be made of the same
    grain rather than of a second kind of noise that does not match.

    One unit of ``x``/``z`` is one feature of the coarsest octave, so a caller
    working in metres divides by the size it wants the features to be.
    """
    return _fbm(np.asarray(x, dtype=np.float64), np.asarray(z, dtype=np.float64),
                seed=seed, octaves=octaves, lacunarity=lacunarity, gain=gain)


def ridged(x: np.ndarray, z: np.ndarray, seed: int = 0,
           octaves: int = 5) -> np.ndarray:
    """Ridged fractal noise over ``(x, z)``, from 0 to 1.

    The same noise folded about its middle, which turns rounded hills into
    ridges with sharp crests -- what mountains are made of here.
    """
    return _ridged(np.asarray(x, dtype=np.float64),
                   np.asarray(z, dtype=np.float64), seed=seed, octaves=octaves)


# --- terrain height + colour --------------------------------------------------

@dataclass(frozen=True)
class TerrainProfile:
    """How tall and how wide each of a landscape's shapes is.

    The generator is four things added together, and a landscape is which of
    them there is how much of: broad rolling **hills**; ridged **mountains**
    under a mask, so they stand in ranges rather than everywhere; a meandering
    **canyon** cut into whatever is above it; and a broad **basin** dished out
    of one region, whose floor is where a lake sits.

    Every amount is metres of relief; the widths and scales are metres on the
    ground. ``seed`` chooses which landscape of that description you get.
    """

    #: Metres from the trough of the rolling hills to their crest.
    hills: float = 45.0
    #: How far apart those hills are, in metres.
    hill_scale: float = 1.0 / 0.0016
    #: Metres from the foot of a range to the top of its ridges.
    mountains: float = 360.0
    #: How far apart the ridges are, in metres.
    mountain_scale: float = 1.0 / 0.0011
    #: How much of the map the ranges cover, from 0 (none) to 1 (everywhere).
    mountain_cover: float = 0.60
    #: How deep the river canyon is cut, in metres.
    canyon: float = 120.0
    #: How wide it is, in metres, measured to where it has half faded out.
    canyon_width: float = 70.0
    #: How far the canyon wanders from a straight line, in metres.
    canyon_meander: float = 240.0
    #: How deep the lake basin is dished out, in metres.
    basin: float = 60.0
    #: How wide the basin's low ground is, in metres.
    basin_scale: float = 1.0 / 0.0009
    #: Where a featureless landscape sits, in metres above the waterline.
    datum: float = 20.0
    #: Which landscape of this description. Every noise field is offset from
    #: it, so two profiles differing only in seed share no feature.
    seed: int = 0

    def to_json(self) -> dict:
        """This profile as a document -- one number per field."""
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_json(cls, document: dict) -> 'TerrainProfile':
        known = {name: document[name] for name in cls.__dataclass_fields__
                 if name in document}
        return cls(**known)


def _scale(metres: float) -> float:
    """A feature size in metres as the frequency the noise is sampled at."""
    return 1.0 / max(float(metres), 1e-6)


def terrain_height_for(profile: TerrainProfile) -> HeightFn:
    """A height function for one profile: metres of ground over ``(x, z)``.

    The result is an ordinary height function, so everything that samples
    terrain takes one of these without knowing a profile exists.
    """
    seed = int(profile.seed)

    def height(x: np.ndarray, z: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        h = np.full(np.broadcast(x, z).shape, float(profile.datum))
        if profile.hills:
            h = h + profile.hills * (
                _fbm(x * _scale(profile.hill_scale),
                     z * _scale(profile.hill_scale),
                     seed=1 + seed, octaves=5) - 0.5)
        if profile.mountains:
            # The mask is what keeps ranges in ranges: mountains everywhere is
            # noise, and a landscape is read by where the high ground is not.
            edge = 1.0 - float(profile.mountain_cover)
            mask = _smooth(np.clip(
                (_fbm(x * 0.0006 + 5, z * 0.0006 - 3, seed=7 + seed, octaves=3)
                 - edge) / 0.28, 0.0, 1.0))
            h = h + profile.mountains * _ridged(
                x * _scale(profile.mountain_scale),
                z * _scale(profile.mountain_scale),
                seed=3 + seed, octaves=6) * mask
        if profile.canyon:
            # A meandering channel carved deep where the ground is near its path.
            path = (profile.canyon_meander * np.sin(z * 0.0016)
                    + profile.canyon_meander * 0.5 * np.sin(z * 0.0007 + 1.3))
            h = h - profile.canyon * np.exp(
                -((x - path) / max(float(profile.canyon_width), 1e-6)) ** 2)
        if profile.basin:
            floor = _smooth(np.clip(
                (_fbm(x * _scale(profile.basin_scale) - 8,
                      z * _scale(profile.basin_scale) + 4,
                      seed=9 + seed, octaves=4) - 0.5) / 0.25, 0.0, 1.0))
            h = h - profile.basin * floor
        return h

    return height


#: The landscape this module has always generated, and every world already
#: baked from it. The numbers are what :func:`terrain_height` used inline.
SHIPPED_TERRAIN = TerrainProfile()

#: The shipped landscape as a height function.
terrain_height: HeightFn = terrain_height_for(SHIPPED_TERRAIN)


def terrain_colors(positions: np.ndarray, normals: np.ndarray,
                   water_level: Optional[float] = None) -> np.ndarray:
    """Per-vertex RGB (N,3) from height and slope, with noise mottling.

    Vectorised. Grass varies between lush and dry tones over broad patches, with a
    finer brightness mottle and dirt/rock breaking through on slopes, so the ground
    reads as varied grass/weeds rather than a flat green sheet.

    ``water_level`` paints anything at or under it as water, which is what a
    surface *clamped* flat at the waterline wants. A world whose water is its
    own geometry (:mod:`OpenGLContext.scenegraph.water`) leaves it out: the
    ground under a lake is its bed, seen through the water, and painting it
    blue as well makes the shallows opaque.
    """
    x = positions[:, 0].astype("d")
    y = positions[:, 1].astype("d")
    z = positions[:, 2].astype("d")
    up = np.clip(normals[:, 1], 0.0, 1.0)          # 1 = flat, 0 = cliff

    water = np.array([0.10, 0.27, 0.42])
    sand = np.array([0.66, 0.60, 0.40])
    grass_lush = np.array([0.17, 0.40, 0.11])
    grass_dry = np.array([0.42, 0.44, 0.19])
    dirt = np.array([0.33, 0.26, 0.17])
    rock = np.array([0.34, 0.30, 0.26])
    snow = np.array([0.92, 0.94, 0.97])

    # Broad biome patches + mid-scale mottle + dirt/rock patches. Frequencies are
    # kept low enough that the terrain mesh actually samples them (fine detail below
    # the vertex spacing would just alias to noise) — ground foliage supplies the
    # close-up detail the mesh can't.
    patch = _value_noise(x * 0.014, z * 0.014, 42)
    mid = _value_noise(x * 0.05, z * 0.05, 17)
    dirtn = _value_noise(x * 0.035 + 3, z * 0.035 - 5, 88)
    rockn = _value_noise(x * 0.045 - 7, z * 0.045 + 2, 55)

    grass = _lerp(grass_lush, grass_dry, patch[:, None])
    grass = grass * (0.68 + 0.62 * mid)[:, None]              # stronger brightness mottle
    grass = _lerp(grass, dirt, np.clip((dirtn - 0.60) / 0.20, 0, 1)[:, None] * 0.85)
    grass = _lerp(grass, rock, np.clip((rockn - 0.74) / 0.15, 0, 1)[:, None] * 0.7)

    t_sand = np.clip((y - 0.5) / 7.5, 0, 1)[:, None]
    t_rock = np.clip((y - 70.0) / 110.0, 0, 1)[:, None]
    t_snow = np.clip((y - 130.0) / 80.0, 0, 1)[:, None]

    col = _lerp(sand, grass, t_sand)                          # shoreline -> grass
    col = _lerp(col, rock, t_rock)                            # grass -> rock
    col = _lerp(col, snow, t_snow)                            # rock -> snow
    # Steep faces expose rock regardless of height.
    steep = np.clip((0.6 - up) / 0.6, 0, 1)[:, None]
    col = _lerp(col, rock * (0.85 + 0.3 * mid)[:, None], steep * 0.85)
    if water_level is not None:
        col = np.where((y <= water_level + 0.5)[:, None], water, col)
    return col.astype("f4")


def _lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    return a * (1.0 - t) + b * t


# --- meshing + glb bake -------------------------------------------------------

def terrain_patch(
    x0: float,
    x1: float,
    z0: float,
    z1: float,
    res: int,
    height_fn: Optional[HeightFn] = None,
    skirt_depth: float = 0.0,
    water_level: Optional[float] = WATER_LEVEL,
    color_fn: Optional[ColorFn] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Mesh a sub-region as (positions, normals, colors, indices).

    `height_fn(x, z)` supplies heights (arbitrary numpy shapes); defaults to the
    built-in procedural field. A DEM loader passes an image-sampling function here.
    `skirt_depth` > 0 drops a vertical skirt around the tile edge so seams between
    adjacent LOD tiles show no gaps.

    `water_level` clamps the surface up to a flat sheet at that height and gives
    it an up normal; `None` meshes the height field as it is, which is what a
    world whose water is its own geometry
    (:mod:`OpenGLContext.scenegraph.water`) wants. `color_fn(positions, normals)`
    supplies per-vertex colour, defaulting to the procedural landscape palette --
    which, where the surface is clamped, is also told the waterline so it paints
    that sheet as water rather than as the ground it stood in for.
    """
    if height_fn is None:
        height_fn = terrain_height
    if color_fn is None:
        color_fn = terrain_colors
    xs = np.linspace(x0, x1, res)
    zs = np.linspace(z0, z1, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gy = height_fn(gx, gz)
    if water_level is not None:
        gy = np.maximum(gy, water_level)            # flat water surface
    pos = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3).astype(np.float32)

    # Normals from central differences of the height field.
    eps = max((x1 - x0), (z1 - z0)) / (res * 4.0) + 1e-3
    hx = height_fn(gx + eps, gz) - height_fn(gx - eps, gz)
    hz = height_fn(gx, gz + eps) - height_fn(gx, gz - eps)
    nrm = np.stack([-hx, np.full_like(hx, 2.0 * eps), -hz], axis=-1)
    nrm = (nrm / np.linalg.norm(nrm, axis=-1, keepdims=True)).reshape(-1, 3)
    if water_level is not None:
        # Water areas get an up normal (flat surface).
        is_water = (gy <= water_level + 1e-4).reshape(-1)
        nrm[is_water] = (0.0, 1.0, 0.0)
    nrm = nrm.astype(np.float32)

    # A patch that clamps at a waterline has a flat sheet on it, and the colour
    # function is told so it can paint that sheet as water. One meshed as it is
    # has a lake *bed*, and the water over it is its own surface.
    col = (color_fn(pos, nrm, water_level) if water_level is not None
           and color_fn is terrain_colors else color_fn(pos, nrm))

    idx_list: list[int] = []
    for i in range(res - 1):
        for j in range(res - 1):
            a = i * res + j
            b = a + 1
            c = a + res
            d = c + 1
            idx_list += [a, b, c, b, d, c]
    idx = np.array(idx_list, "<u4")
    if skirt_depth > 0.0:
        pos, nrm, col, idx = _add_skirt(pos, nrm, col, idx, res, skirt_depth)
    return pos, nrm, col, idx


def _perimeter_indices(res: int) -> list[int]:
    """Ordered vertex indices around the grid border (a closed loop)."""
    top = [0 * res + j for j in range(res)]
    right = [i * res + (res - 1) for i in range(1, res)]
    bottom = [(res - 1) * res + j for j in range(res - 2, -1, -1)]
    left = [i * res + 0 for i in range(res - 2, 0, -1)]
    return top + right + bottom + left


def _add_skirt(
    pos: np.ndarray,
    nrm: np.ndarray,
    col: np.ndarray,
    idx: np.ndarray,
    res: int,
    depth: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Drop a vertical skirt around the tile edge to hide gaps between LOD tiles."""
    loop = _perimeter_indices(res)
    base = len(pos)
    lowered = pos[loop].copy()
    lowered[:, 1] -= depth
    skirt_nrm = np.tile(np.array([0.0, 0.0, 1.0], "f4"), (len(loop), 1))
    skirt_col = col[loop].copy()
    new_pos = np.vstack([pos, lowered.astype("f4")])
    new_nrm = np.vstack([nrm, skirt_nrm])
    new_col = np.vstack([col, skirt_col])
    quads = []
    n = len(loop)
    for k in range(n):
        a = loop[k]
        b = loop[(k + 1) % n]
        a2 = base + k
        b2 = base + (k + 1) % n
        quads += [a, a2, b, b, a2, b2]
    new_idx = np.concatenate([idx, np.array(quads, "<u4")])
    return new_pos, new_nrm, new_col, new_idx


def _bounding_box(pos: np.ndarray) -> list[float]:
    mins = pos.min(0)
    maxs = pos.max(0)
    center = (mins + maxs) / 2.0
    half = np.maximum((maxs - mins) / 2.0, 1e-3)
    # The mesh is Y-up, as glTF is; a tile's own frame is Z-up, as 3D Tiles is.
    # So the box is stated in that frame -- the mesh's height becomes the box's
    # Z extent -- and a client turns the content the same quarter turn to match.
    return [float(center[0]), float(-center[2]), float(center[1]),
            float(half[0]), 0.0, 0.0,
            0.0, float(half[2]), 0.0,
            0.0, 0.0, float(half[1])]


def _glb(
    pos: np.ndarray, nrm: np.ndarray, col: np.ndarray, idx: np.ndarray
) -> bytes:
    """One tile's mesh as binary glTF: vertex-coloured, unlit-white, two-sided.

    Two-sided because a tile's skirt is seen from inside the terrain as often as
    from outside it.
    """
    from OpenGLContext.loaders.gltf.writer import write_glb
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    mesh = PBRMesh(
        positions=np.asarray(pos, "f"), normals=np.asarray(nrm, "f"),
        colors=np.asarray(col, "f"), indices=np.asarray(idx, np.uint32),
        material=PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0,
                             roughness=1.0, doubleSided=True))
    return write_glb(mesh)


def build_terrain_tileset(
    directory: str,
    extent: float = 2048.0,
    levels: int = 3,
    tile_res: int = 33,
    height_fn: Optional[HeightFn] = None,
) -> str:
    """Bake a quadtree of terrain tiles into `directory`; return tileset.json path.

    `levels` quadtree depth (level L has 4**L tiles); every tile is meshed at
    `tile_res`, so deeper tiles cover less ground at the same vertex count (finer
    detail). Total tiles = sum(4**l for l in 0..levels-1). REPLACE refinement.
    `height_fn` overrides the procedural height field (e.g. a DEM sampler).
    """
    os.makedirs(directory, exist_ok=True)

    def build(level: int, cx: float, cz: float, size: float) -> dict[str, Any]:
        h = size / 2.0
        # Skirt depth scales with tile ground size so seams close at every level.
        pos, nrm, col, idx = terrain_patch(cx - h, cx + h, cz - h, cz + h,
                                           tile_res, height_fn=height_fn,
                                           skirt_depth=size / tile_res * 2.0)
        name = "t_%d_%d_%d.glb" % (level, int(cx), int(cz))
        with open(os.path.join(directory, name), "wb") as fh:
            fh.write(_glb(pos, nrm, col, idx))
        node = {
            "boundingVolume": {"box": _bounding_box(pos)},
            "geometricError": size / tile_res * 1.5,
            "content": {"uri": name},
        }
        if level < levels - 1:
            q = size / 4.0
            node["refine"] = "REPLACE"
            node["children"] = [
                build(level + 1, cx - q, cz - q, size / 2.0),
                build(level + 1, cx + q, cz - q, size / 2.0),
                build(level + 1, cx - q, cz + q, size / 2.0),
                build(level + 1, cx + q, cz + q, size / 2.0),
            ]
        return node

    root = build(0, 0.0, 0.0, extent)
    root["geometricError"] = extent / tile_res * 1.5
    tileset = {"asset": {"version": "1.1"},
               "geometricError": extent / tile_res * 3.0, "root": root}
    path = os.path.join(directory, "tileset.json")
    with open(path, "w") as fh:
        json.dump(tileset, fh)
    return path
