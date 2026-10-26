"""Helpers the OBJ corpus tests share: the corpus, its manifest, and arithmetic on what was read.

``tests/unit/obj_corpus/manifest.json`` states, for each file of the corpus, what
a correct reader finds in it: triangle count, surface area, bounds, part and
material names, and vertex count where the file's normals and smoothing fix it.
The numbers are worked out from the geometry the file describes, not from this
reader's output.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np

from OpenGLContext.loaders.objfile import ObjFile, parse_obj

CORPUS = Path(__file__).resolve().parent / 'obj_corpus'
MANIFEST = json.loads((CORPUS / 'manifest.json').read_text(encoding='utf-8'))
NAMES = sorted(MANIFEST)


def read(name: str) -> ObjFile:
    return parse_obj((CORPUS / name).read_bytes(), name)


def corner_positions(model: ObjFile) -> np.ndarray:
    """Every triangle of the model as ``(n, 3, 3)`` corner positions"""
    found = [mesh.positions[mesh.indices.reshape(-1, 3)]
             for part in model.parts for mesh in part.meshes if mesh.kind == 'triangles']
    return np.concatenate(found) if found else np.zeros((0, 3, 3), np.float32)


def crosses(triangles: np.ndarray) -> np.ndarray:
    corners = triangles.astype(np.float64)
    return np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])


def surface_area(triangles: np.ndarray) -> float:
    return float(np.linalg.norm(crosses(triangles), axis=1).sum() / 2) if len(triangles) else 0.0


def bounds_of(model: ObjFile) -> Any:
    positions = [mesh.positions for part in model.parts for mesh in part.meshes]
    if not positions:
        return None
    every = np.concatenate(positions)
    return [every.min(axis=0).tolist(), every.max(axis=0).tolist()]


def check_consistent(model: ObjFile) -> None:
    """The invariants every successful read holds, whatever the file said"""
    for part in model.parts:
        assert part.meshes, 'a part with no meshes'
        for mesh in part.meshes:
            count = len(mesh.positions)
            assert mesh.positions.dtype == np.float32 and mesh.positions.shape == (count, 3)
            assert mesh.indices.dtype == np.uint32
            assert len(mesh.indices) and int(mesh.indices.max()) < count
            assert np.isfinite(mesh.positions).all()
            width = {'triangles': 3, 'lines': 2, 'points': 1}[mesh.kind]
            assert len(mesh.indices) % width == 0
            if mesh.kind == 'triangles':
                assert mesh.normals is not None and mesh.normals.shape == (count, 3)
                assert np.isfinite(mesh.normals).all()
                lengths = np.linalg.norm(mesh.normals, axis=1)
                assert np.allclose(lengths, 1.0, atol=1e-4)
            else:
                assert mesh.normals is None
            if mesh.texcoords is not None:
                assert mesh.texcoords.shape == (count, 2) and np.isfinite(mesh.texcoords).all()
            if mesh.colors is not None:
                assert mesh.colors.shape == (count, 4) and np.isfinite(mesh.colors).all()


def convex_polygon(rng: np.random.Generator, corners: int) -> np.ndarray:
    """A convex polygon with ``corners`` corners in a random plane, counter-clockwise from its normal"""
    angles = np.sort(rng.uniform(0, 2 * np.pi, corners))
    while np.diff(np.concatenate([angles, [angles[0] + 2 * np.pi]])).max() > np.pi * 0.9:
        angles = np.sort(rng.uniform(0, 2 * np.pi, corners))
    flat = np.stack([np.cos(angles), np.sin(angles), np.zeros(corners)], axis=1) * rng.uniform(0.5, 2.0)
    quaternion = rng.normal(size=4)
    quaternion /= np.linalg.norm(quaternion)
    w, x, y, z = quaternion
    rotation = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    return flat @ rotation.T + rng.uniform(-3, 3, 3)


def random_obj(seed: int) -> str:
    """An OBJ of convex polygons, written with every corner form and statement mix

    Every vertex, texture coordinate and normal is written before the first
    face, which is the one order in which a relative index means the same to
    every reader.
    """
    rng = np.random.default_rng(seed)
    pick = random.Random(seed)
    eol = pick.choice(['\n', '\r\n'])
    lines: list[str] = ['# random polygons %d' % seed]
    polygons = [convex_polygon(rng, int(rng.integers(3, 9))) for _ in range(int(rng.integers(3, 12)))]
    firsts = []
    for polygon in polygons:
        firsts.append(sum(len(other) for other in polygons[:len(firsts)]))
        lines.extend('v %.7f %.7f %.7f' % tuple(point) for point in polygon)
    total = sum(len(polygon) for polygon in polygons)
    lines.extend('vt %.4f %.4f' % (pick.random(), pick.random()) for _ in range(total))
    lines.extend('vn 0.0 0.0 1.0' for _ in range(total))
    relative = pick.random() < 0.5
    for polygon, first in zip(polygons, firsts):
        if pick.random() < 0.4:
            lines.append(pick.choice(['g group%d' % pick.randrange(3), 'o object%d' % pick.randrange(3),
                                      'usemtl m%d' % pick.randrange(3), 's %d' % pick.randrange(3),
                                      's off', '# a comment']))
        form = pick.choice(['v', 'v/t', 'v//n', 'v/t/n'])
        corners = []
        for corner in range(len(polygon)):
            absolute = first + corner + 1
            shown = absolute - total - 1 if relative else absolute
            corners.append({'v': '%d', 'v/t': '%d/%d', 'v//n': '%d//%d', 'v/t/n': '%d/%d/%d'}[form]
                           % {'v': (shown,), 'v/t': (shown, shown), 'v//n': (shown, shown),
                              'v/t/n': (shown, shown, shown)}[form])
        lines.append('f ' + ' '.join(corners))
    return eol.join(lines) + eol


def damaged(data: bytes, seed: int) -> bytes:
    """``data`` with one deterministic injury: a dropped, repeated or swapped line, a cut, or a bad token"""
    pick = random.Random(seed)
    lines = data.split(b'\n')
    kind = pick.randrange(7)
    if kind == 0 and lines:
        del lines[pick.randrange(len(lines))]
    elif kind == 1 and lines:
        at = pick.randrange(len(lines))
        lines.insert(at, lines[at])
    elif kind == 2 and len(lines) > 1:
        a, b = pick.randrange(len(lines)), pick.randrange(len(lines))
        lines[a], lines[b] = lines[b], lines[a]
    elif kind == 3:
        return data[:pick.randrange(len(data) + 1)]
    elif kind == 4 and lines:
        at = pick.randrange(len(lines))
        tokens = lines[at].split(b' ')
        tokens[pick.randrange(len(tokens))] = pick.choice(
            [b'x', b'-1', b'0', b'1e999', b'nan', b'999999', b'/', b'//', b'1/2/3/4', b'', b'-0'])
        lines[at] = b' '.join(tokens)
    elif kind == 5:
        lines.insert(pick.randrange(len(lines) + 1), pick.choice(
            [b'f', b'f 1', b'l 1', b'p', b'v 1', b'vt', b'vn 1 2', b'o', b'g', b's', b's x',
             b'usemtl', b'mtllib', b'f 1/1/1/1 2 3', b'\\', b'f 1 \\', b'#']))
    else:
        index = pick.randrange(len(data)) if data else 0
        return data[:index] + bytes([pick.randrange(256)]) + data[index + 1:]
    return b'\n'.join(lines)
