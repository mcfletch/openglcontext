"""glTF primitive -> renderable Shape, with normal/tangent/morph handling.

Decodes a mesh primitive into an OpenGLContext ``Shape`` wrapping a ``PBRMesh``:
reads its vertex attributes (position/normal/texcoord/tangent/colour/skin) through
:mod:`accessors`, resolves its material through :mod:`materials`, triangulates
strip/fan primitives to a GL triangle list, and fills in what the asset omits --
face-estimated normals and, for normal-mapped primitives with no supplied
tangents, Lengyel-method tangents -- so authored maps actually shade. Attribute
counts and index ranges are validated up front, so a malformed primitive reports
which attribute disagrees instead of crashing in the VBO upload.

Also reads a primitive's morph ``targets`` (position/normal/tangent deltas) for the
animation Player to blend per frame.
"""
from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, Any, Optional, Tuple

import numpy as np

from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.loaders.resolver import Resolver

if TYPE_CHECKING:
    import pygltflib
    # ``Shape``/``Appearance`` are registered into basenodes dynamically (plugin
    # entry points), so mypy cannot see them there; take the types from their
    # defining modules.
    from OpenGLContext.scenegraph.shape import Shape
    from OpenGLContext.scenegraph.appearance import Appearance
else:
    from OpenGLContext.scenegraph.basenodes import Shape, Appearance
from OpenGLContext.loaders.gltf.accessors import (
    _read_floats, _read_accessor, _read_texcoords, _read_normalized, _read_colors,
)
from OpenGLContext.loaders.gltf.materials import _build_material
from OpenGLContext.loaders.gltf.transforms import _bounds_from_points
from OpenGLContext.loaders.gltf import draco as _draco

log = logging.getLogger(__name__)


class PrimitiveMode(enum.IntEnum):
    """glTF ``primitive.mode``; each value equals the matching GL primitive enum."""
    POINTS = 0
    LINES = 1
    LINE_LOOP = 2
    LINE_STRIP = 3
    TRIANGLES = 4
    TRIANGLE_STRIP = 5
    TRIANGLE_FAN = 6


def _triangulate_indices(mode: Optional[int], indices: Optional[np.ndarray],
                         vertex_count: int) -> Tuple[Optional[np.ndarray], Optional[int]]:
    """Map a primitive's (mode, indices) to a (indices, gl_draw_mode) pair.

    The glTF primitive.mode enum equals the GL primitive enum (POINTS=0 … TRIANGLES=4),
    so POINTS/LINES/LINE_LOOP/LINE_STRIP pass their indices through and report their own
    GL mode -- the mesh draws them as points/lines rather than skipping them (which left
    the point/line columns of PrimitiveModeNormalsTest / MeshPrimitiveModes empty).
    Plain TRIANGLES pass through (``None`` stays ``None`` -> non-indexed glDrawArrays);
    strip/fan are expanded to an explicit GL_TRIANGLES list.
    """
    if mode is None or mode == PrimitiveMode.TRIANGLES:
        return indices, PrimitiveMode.TRIANGLES
    if mode in (PrimitiveMode.POINTS, PrimitiveMode.LINES,
                PrimitiveMode.LINE_LOOP, PrimitiveMode.LINE_STRIP):
        return indices, mode                      # glTF mode == GL enum
    if mode in (PrimitiveMode.TRIANGLE_STRIP, PrimitiveMode.TRIANGLE_FAN):
        src = indices if indices is not None else np.arange(vertex_count, dtype=np.uint32)
        n = len(src)
        if n < 3:
            return None, PrimitiveMode.TRIANGLES
        tris: list = []
        if mode == PrimitiveMode.TRIANGLE_STRIP:
            for i in range(n - 2):
                # every other triangle flips winding to keep a consistent facing
                a, b, c = (i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2)
                tris.extend((src[a], src[b], src[c]))
        else:  # TRIANGLE_FAN: all triangles share vertex 0
            for i in range(1, n - 1):
                tris.extend((src[0], src[i], src[i + 1]))
        return np.asarray(tris, dtype=np.uint32), PrimitiveMode.TRIANGLES
    return None, None


def _primitive_shape(g: "pygltflib.GLTF2", primitive: "pygltflib.Primitive",
                     resolver: Resolver, mat_cache: dict, tex_cache: dict
                     ) -> Tuple[Optional["Shape"], Optional[Tuple[np.ndarray, np.ndarray]]]:
    attrs = primitive.attributes
    if attrs.POSITION is None:
        return None, None
    if _draco.draco_extension(primitive) is not None:
        try:
            arrays = _draco.draco_arrays(g, primitive, resolver)
        except ValueError as err:
            # A malformed Draco stream (bad bufferView, no POSITION, an attribute
            # with no accessor) raises here. Skip just this primitive and keep
            # loading the scene, matching the DracoPy-absent path below rather than
            # aborting the whole load. Scoped to the decode step so a non-Draco bug
            # downstream still surfaces.
            log.warning("glTF: skipping malformed Draco primitive: %s", err)
            return None, None
        if arrays is None:                       # DracoPy absent -> skip primitive
            return None, None
        positions = arrays['positions']
        indices = arrays['indices']
        normals, texcoords = arrays.get('normals'), arrays.get('texcoords')
        texcoords1, tangents = arrays.get('texcoords1'), arrays.get('tangents')
        colors = arrays.get('colors')
        skin_joints, skin_weights = arrays.get('skin_joints'), arrays.get('skin_weights')
    else:
        positions = _read_floats(g, attrs.POSITION, resolver)
        indices = None
        if primitive.indices is not None:
            indices = _read_accessor(g, primitive.indices, resolver).astype(np.uint32).ravel()
        normals = _read_floats(g, attrs.NORMAL, resolver) if attrs.NORMAL is not None else None
        texcoords = (_read_texcoords(g, attrs.TEXCOORD_0, resolver)
                     if attrs.TEXCOORD_0 is not None else None)
        texcoords1 = (_read_texcoords(g, attrs.TEXCOORD_1, resolver)
                      if getattr(attrs, 'TEXCOORD_1', None) is not None else None)
        tangents = _read_floats(g, attrs.TANGENT, resolver) if attrs.TANGENT is not None else None
        colors = _read_colors(g, attrs.COLOR_0, resolver) if attrs.COLOR_0 is not None else None
        skin_joints = (_read_accessor(g, attrs.JOINTS_0, resolver).astype(np.uint32)
                       if getattr(attrs, 'JOINTS_0', None) is not None else None)
        skin_weights = (_read_normalized(g, attrs.WEIGHTS_0, resolver)
                        if getattr(attrs, 'WEIGHTS_0', None) is not None else None)
    indices, draw_mode = _triangulate_indices(
        getattr(primitive, 'mode', None), indices, len(positions))
    if draw_mode is None:
        log.warning("glTF: skipping primitive with unknown mode %s",
                    getattr(primitive, 'mode', None))
        return None, None
    # Vertex attributes must all describe the same vertices, and indices must land
    # inside them; validate up front so a malformed primitive reports which
    # attribute disagrees rather than crashing deep in the VBO upload (3.11).
    nverts = len(positions)
    for name, arr in (('NORMAL', normals), ('TEXCOORD_0', texcoords),
                      ('TEXCOORD_1', texcoords1),
                      ('TANGENT', tangents), ('COLOR_0', colors),
                      ('JOINTS_0', skin_joints), ('WEIGHTS_0', skin_weights)):
        if arr is not None and len(arr) != nverts:
            raise ValueError(
                "glTF primitive attribute %s has %d entries but POSITION has %d"
                % (name, len(arr), nverts))
    if indices is not None and len(indices):
        max_idx = int(indices.max())
        if max_idx >= nverts:
            raise ValueError(
                "glTF primitive index %d is out of range for %d vertices"
                % (max_idx, nverts))
    if normals is None:
        # Face-normal estimation only makes sense for triangles; points/lines get a
        # constant up-normal so the lit shader still shades them predictably.
        normals = (estimate_normals(positions, indices)
                   if draw_mode == PrimitiveMode.TRIANGLES
                   else np.tile(np.array([0, 0, 1], 'f'), (nverts, 1)))

    key = primitive.material
    material = mat_cache.get(key)
    if material is None:
        material = _build_material(g, key, resolver, tex_cache)
        mat_cache[key] = material

    # A normal-mapped primitive that ships no tangents renders flat (the shader
    # disables normal mapping when the tangent is zero). The glTF spec says the
    # client SHOULD compute tangents in that case; do so, mirroring the missing-
    # normal fallback above, so authored normal maps actually perturb the surface.
    if (tangents is None and texcoords is not None
            and 'normal' in getattr(material, 'textures', {})):
        tangents = estimate_tangents(positions, normals, texcoords, indices)

    morph_targets = _read_morph_targets(g, primitive, resolver, nverts)
    mesh = PBRMesh(positions=positions, normals=normals, texcoords=texcoords,
                   texcoords1=texcoords1, tangents=tangents, colors=colors,
                   indices=indices, material=material, morph_targets=morph_targets,
                   skin_joints=skin_joints, skin_weights=skin_weights,
                   draw_mode=int(draw_mode),
                   solid=not bool(getattr(material, 'doubleSided', False)))
    shape = Shape(geometry=mesh, appearance=Appearance(material=material))
    acc = g.accessors[attrs.POSITION]
    bounds = (np.asarray(acc.min, dtype='d'), np.asarray(acc.max, dtype='d')) \
        if acc.min and acc.max else _bounds_from_points(positions)
    return shape, bounds


def _read_morph_targets(g: "pygltflib.GLTF2", primitive: "pygltflib.Primitive",
                        resolver: Resolver, nverts: int) -> Optional[list]:
    """Read a primitive's morph ``targets`` into position/normal/tangent deltas.

    Each target is a dict/object with any of POSITION, NORMAL, TANGENT accessors
    (all VEC3 deltas -- tangent morphs the xyz only, per the spec). A target whose
    array disagrees with the base vertex count is dropped with a warning rather
    than corrupting the deform. Returns None when the primitive has no targets.
    """
    targets = getattr(primitive, 'targets', None)
    if not targets:
        return None

    def acc(t: Any, name: str) -> Any:
        return t.get(name) if isinstance(t, dict) else getattr(t, name, None)

    out = []
    for t in targets:
        entry = {}
        for gltf_name, key in (('POSITION', 'positions'), ('NORMAL', 'normals'),
                               ('TANGENT', 'tangents')):
            ai = acc(t, gltf_name)
            if ai is None:
                continue
            arr = _read_floats(g, ai, resolver)
            if len(arr) != nverts:
                log.warning("glTF: morph target %s has %d entries but the base "
                            "mesh has %d; ignoring it", gltf_name, len(arr), nverts)
                continue
            entry[key] = arr
        out.append(entry)
    return out


def estimate_normals(positions: np.ndarray, indices: Optional[np.ndarray]) -> np.ndarray:
    """Per-vertex normals from the triangles that share each vertex.

    What a mesh with no NORMAL attribute is shaded by, and what any generated
    surface -- a road, an extrusion, a lofted shape -- gets its normals from:
    each triangle's face normal is accumulated onto its three vertices and the
    sum normalised, which smooths across a shared edge and keeps a hard one
    hard where the vertices are split.
    """
    normals = np.zeros_like(positions)
    if indices is None:
        idx = np.arange(len(positions), dtype=np.uint32)
    else:
        idx = indices
    usable = (len(idx) // 3) * 3   # ignore a trailing partial triangle
    tris = idx[:usable].reshape(-1, 3)
    if not len(tris):
        return normals
    v0, v1, v2 = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    for i in range(3):
        np.add.at(normals, tris[:, i], fn)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    return np.ascontiguousarray((normals / lens).astype(np.float32))


def estimate_tangents(positions: np.ndarray, normals: np.ndarray, texcoords: np.ndarray,
                       indices: Optional[np.ndarray]) -> np.ndarray:
    """Per-vertex tangents (vec4 xyz + w handedness) from UVs, for normal mapping.

    Lengyel's method: accumulate each triangle's UV-derived tangent/bitangent onto
    its vertices, then Gram-Schmidt the tangent against the vertex normal and set
    w to the bitangent handedness -- exactly the vec4 the pbr shader expects at
    attribute location 3. A vertex left with a zero tangent (degenerate UVs) makes
    the shader fall back to the geometric normal there, which is harmless."""
    n = len(positions)
    idx = np.arange(n, dtype=np.uint32) if indices is None else indices
    usable = (len(idx) // 3) * 3
    tris = idx[:usable].reshape(-1, 3)
    if not len(tris):
        return np.zeros((n, 4), np.float32)
    pos = positions.astype(np.float64)
    uv = texcoords.astype(np.float64)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    uv0, uv1, uv2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    du1, dv1 = (uv1 - uv0)[:, 0], (uv1 - uv0)[:, 1]
    du2, dv2 = (uv2 - uv0)[:, 0], (uv2 - uv0)[:, 1]
    denom = du1 * dv2 - du2 * dv1
    r = np.zeros_like(denom)
    nz = np.abs(denom) > 1e-12
    r[nz] = 1.0 / denom[nz]
    tri_t = (e1 * dv2[:, None] - e2 * dv1[:, None]) * r[:, None]
    tri_b = (e2 * du1[:, None] - e1 * du2[:, None]) * r[:, None]
    tan = np.zeros((n, 3), np.float64)
    bit = np.zeros((n, 3), np.float64)
    for i in range(3):
        np.add.at(tan, tris[:, i], tri_t)
        np.add.at(bit, tris[:, i], tri_b)
    nrm = normals.astype(np.float64)
    tang = tan - nrm * np.sum(nrm * tan, axis=1, keepdims=True)   # Gram-Schmidt
    lens = np.linalg.norm(tang, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    tang = tang / lens
    # Handedness. glTF's shader reconstructs the bitangent as cross(N,T)*w and its
    # normal maps follow the OpenGL green-up (V-flipped image) convention, so the
    # correct w is the *negation* of Lengyel's raw sign (which assumes B points along
    # increasing V). Verified against the reference tangents supplied by
    # NormalTangentMirrorTest: this sign makes all 2770 vertices match; the raw sign
    # mismatches all of them and shows a hard dark band on rotated-UV cells.
    w = -np.sign(np.sum(np.cross(nrm, tang) * bit, axis=1))
    w[w == 0] = 1.0
    out = np.empty((n, 4), np.float32)
    out[:, :3] = tang
    out[:, 3] = w
    return np.ascontiguousarray(out)
