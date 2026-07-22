"""Generate a small heightfield 3D Tiles dataset for demos and tests.

Bakes a two-level quadtree: a coarse root tile over the whole region and four finer
child tiles over its quadrants (REPLACE refinement), each a glTF heightfield mesh
with per-vertex normals and a green material. This is a stand-in for the real bake
toolchain (§7) — enough to exercise streaming, LOD, and rendering end to end.
"""
import json
import math
import os

import numpy as np


def _height(x, z, amp=6.0):
    return amp * math.sin(x * 0.06) * math.cos(z * 0.05)


def _grid_mesh(x0, x1, z0, z1, n):
    """A heightfield mesh over [x0,x1]x[z0,z1] as (positions, normals, indices)."""
    xs = np.linspace(x0, x1, n)
    zs = np.linspace(z0, z1, n)
    pos = np.zeros((n, n, 3), "f4")
    nrm = np.zeros((n, n, 3), "f4")
    for i, x in enumerate(xs):
        for j, z in enumerate(zs):
            pos[i, j] = (x, _height(x, z), z)
            # Analytic gradient of the height field for a smooth normal.
            dhdx = 6.0 * 0.06 * math.cos(x * 0.06) * math.cos(z * 0.05)
            dhdz = -6.0 * 0.05 * math.sin(x * 0.06) * math.sin(z * 0.05)
            v = np.array([-dhdx, 1.0, -dhdz], "f4")
            nrm[i, j] = v / np.linalg.norm(v)
    idx = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            b = a + 1
            c = a + n
            d = c + 1
            # Wind CCW seen from above (+Y) so the top surface is front-facing.
            idx += [a, b, c, b, d, c]
    return (pos.reshape(-1, 3), nrm.reshape(-1, 3),
            np.array(idx, "<u4"))


def _bounding_box(pos):
    mins = pos.min(0)
    maxs = pos.max(0)
    center = (mins + maxs) / 2.0
    half = (maxs - mins) / 2.0
    # 3D Tiles box: center, then x/y/z half-axis vectors.
    return [
        float(center[0]), float(center[1]), float(center[2]),
        float(half[0]), 0.0, 0.0,
        0.0, float(half[1]), 0.0,
        0.0, 0.0, float(half[2]),
    ]


def _glb(pos, nrm, idx, color=(0.30, 0.55, 0.25, 1.0)):
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness,
    )
    blob, spans = b"", []
    for arr in (pos.astype("<f4"), nrm.astype("<f4"), idx.astype("<u4")):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type="VEC3",
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type="VEC3"),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type="SCALAR"),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=0)])]
    g.materials = [Material(
        pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorFactor=list(color), metallicFactor=0.0, roughnessFactor=0.9),
        doubleSided=True)]
    g.bufferViews = views
    g.accessors = acc
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _box_mesh(center, size):
    """An axis-aligned box as (positions, normals, indices), outward-facing CCW."""
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    faces = [
        ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
        ((-1, 0, 0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
        ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
    ]
    pos, nrm, idx = [], [], []
    for normal, quad in faces:
        base = len(pos)
        for sx, sy, sz in quad:
            pos.append((cx + sx * hx, cy + sy * hy, cz + sz * hz))
            nrm.append(normal)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(pos, "f4"), np.array(nrm, "f4"), np.array(idx, "<u4"))


def build_overhang_tileset(directory, span=120.0, ground_res=17):
    """Write a tileset with ground plus an elevated slab (an overhang).

    The slab sits above the ground over the same footprint, so a vertical column has
    solid-air-solid-air structure — geometry a heightfield cannot express. It exercises
    the runtime's ability to carry arbitrary 3D (cave/overhang) tiles as glTF octree
    nodes. Returns the tileset.json path.
    """
    os.makedirs(directory, exist_ok=True)
    s = span
    g_pos, g_nrm, g_idx = _grid_mesh(-s, s, -s, s, ground_res)
    with open(os.path.join(directory, "ground.glb"), "wb") as fh:
        fh.write(_glb(g_pos, g_nrm, g_idx, color=(0.15, 0.45, 0.10, 1.0)))

    o_pos, o_nrm, o_idx = _box_mesh(center=(0, 25.0, 0), size=(80.0, 6.0, 80.0))
    with open(os.path.join(directory, "overhang.glb"), "wb") as fh:
        fh.write(_glb(o_pos, o_nrm, o_idx, color=(0.4, 0.32, 0.24, 1.0)))

    tileset = {
        "asset": {"version": "1.1"},
        "geometricError": 80.0,
        "root": {
            "boundingVolume": {"box": _bounding_box(
                np.vstack([g_pos, o_pos]))},
            "geometricError": 40.0,
            "refine": "ADD",
            "children": [
                {"boundingVolume": {"box": _bounding_box(g_pos)},
                 "geometricError": 0.0, "content": {"uri": "ground.glb"}},
                {"boundingVolume": {"box": _bounding_box(o_pos)},
                 "geometricError": 0.0, "content": {"uri": "overhang.glb"}},
            ],
        },
    }
    path = os.path.join(directory, "tileset.json")
    with open(path, "w") as fh:
        json.dump(tileset, fh, indent=2)
    return path


def build_sample_tileset(directory, span=120.0, root_res=9, child_res=17):
    """Write a heightfield tileset (root + 4 children) into `directory`.

    Returns the path to the written tileset.json.
    """
    os.makedirs(directory, exist_ok=True)
    s = span
    root_pos, root_nrm, root_idx = _grid_mesh(-s, s, -s, s, root_res)
    root_bytes = _glb(root_pos, root_nrm, root_idx, color=(0.15, 0.45, 0.10, 1.0))
    with open(os.path.join(directory, "root.glb"), "wb") as fh:
        fh.write(root_bytes)

    quadrants = [(-s, 0, -s, 0), (0, s, -s, 0), (-s, 0, 0, s), (0, s, 0, s)]
    child_defs = []
    for i, (x0, x1, z0, z1) in enumerate(quadrants):
        pos, nrm, idx = _grid_mesh(x0, x1, z0, z1, child_res)
        name = "c%d.glb" % i
        with open(os.path.join(directory, name), "wb") as fh:
            fh.write(_glb(pos, nrm, idx, color=(0.13, 0.5, 0.09, 1.0)))
        child_defs.append({
            "boundingVolume": {"box": _bounding_box(pos)},
            "geometricError": 1.5,
            "content": {"uri": name},
        })

    tileset = {
        "asset": {"version": "1.1"},
        "geometricError": 60.0,
        "root": {
            "boundingVolume": {"box": _bounding_box(root_pos)},
            "geometricError": 25.0,
            "refine": "REPLACE",
            "content": {"uri": "root.glb"},
            "children": child_defs,
        },
    }
    path = os.path.join(directory, "tileset.json")
    with open(path, "w") as fh:
        json.dump(tileset, fh, indent=2)
    return path
