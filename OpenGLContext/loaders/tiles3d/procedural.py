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
from typing import Any, Optional

import numpy as np

HeightFn = Callable[[np.ndarray, np.ndarray], np.ndarray]

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


# --- terrain height + colour --------------------------------------------------

def terrain_height(x: np.ndarray, z: np.ndarray) -> np.ndarray:
    """World-space height (Y) over an (x, z) grid — arbitrary numpy shapes."""
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    hills = 45.0 * (_fbm(x * 0.0016, z * 0.0016, seed=1, octaves=5) - 0.5)
    mask = _smooth(np.clip(
        (_fbm(x * 0.0006 + 5, z * 0.0006 - 3, seed=7, octaves=3) - 0.40) / 0.28,
        0.0, 1.0))
    mountains = 360.0 * _ridged(x * 0.0011, z * 0.0011, seed=3, octaves=6) * mask
    h = 20.0 + hills + mountains
    # River canyon: a meandering channel carved deep where |x - path(z)| is small.
    path = 240.0 * np.sin(z * 0.0016) + 120.0 * np.sin(z * 0.0007 + 1.3)
    canyon = np.exp(-((x - path) / 70.0) ** 2)
    h = h - 120.0 * canyon
    # Lake basin: a broad low region in one quadrant, floor near water level.
    basin = _smooth(np.clip(
        (_fbm(x * 0.0009 - 8, z * 0.0009 + 4, seed=9, octaves=4) - 0.5) / 0.25,
        0.0, 1.0))
    h = h - 60.0 * basin
    return h


def terrain_colors(positions: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Per-vertex RGB (N,3) from height, slope and water, with noise mottling.

    Vectorised. Grass varies between lush and dry tones over broad patches, with a
    finer brightness mottle and dirt/rock breaking through on slopes, so the ground
    reads as varied grass/weeds rather than a flat green sheet.
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
    # Water surface overrides.
    is_water = (y <= WATER_LEVEL + 0.5)[:, None]
    col = np.where(is_water, water, col)
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
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Mesh a sub-region as (positions, normals, colors, indices), water clamped.

    `height_fn(x, z)` supplies heights (arbitrary numpy shapes); defaults to the
    built-in procedural field. A DEM loader passes an image-sampling function here.
    `skirt_depth` > 0 drops a vertical skirt around the tile edge so seams between
    adjacent LOD tiles show no gaps.
    """
    if height_fn is None:
        height_fn = terrain_height
    xs = np.linspace(x0, x1, res)
    zs = np.linspace(z0, z1, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    gy = height_fn(gx, gz)
    gy = np.maximum(gy, WATER_LEVEL)                # flat water surface
    pos = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3).astype(np.float32)

    # Normals from central differences of the height field.
    eps = max((x1 - x0), (z1 - z0)) / (res * 4.0) + 1e-3
    hx = height_fn(gx + eps, gz) - height_fn(gx - eps, gz)
    hz = height_fn(gx, gz + eps) - height_fn(gx, gz - eps)
    nrm = np.stack([-hx, np.full_like(hx, 2.0 * eps), -hz], axis=-1)
    nrm = (nrm / np.linalg.norm(nrm, axis=-1, keepdims=True)).reshape(-1, 3)
    # Water areas get an up normal (flat surface).
    is_water = (gy <= WATER_LEVEL + 1e-4).reshape(-1)
    nrm[is_water] = (0.0, 1.0, 0.0)
    nrm = nrm.astype(np.float32)

    col = terrain_colors(pos, nrm)

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
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness,
    )
    arrays = [pos.astype("<f4"), nrm.astype("<f4"),
              col.astype("<f4"), idx.astype("<u4")]
    blob, spans = b"", []
    for arr in arrays:
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type="VEC3",
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type="VEC3"),
        Accessor(bufferView=2, componentType=5126, count=len(col), type="VEC3"),
        Accessor(bufferView=3, componentType=5125, count=len(idx), type="SCALAR"),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1, COLOR_0=2),
        indices=3, material=0)])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=1.0),
        doubleSided=True)]
    g.bufferViews = views
    g.accessors = acc
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


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
