"""Instanced-geometry support: group render records and draw them in one call.

Large scenes are dominated by the O(N) per-object draw loop (``Shape.Render``).
When many shapes share one geometry (a sphere field, repeated glTF parts, a
scatter of props), they can be collapsed into a single ``glDrawElementsInstanced``
with per-instance data (model matrix, object id, and -- later -- a material index
into a material array). This module owns:

  * the grouping engine (headless, pure): decide which records batch together;
  * GL capability detection: pick the conditional draw path the driver supports.

The grouping is format-neutral, so VRML ``USE``/``DEF`` sharing, glTF shared-mesh
nodes, and ``EXT_mesh_gpu_instancing`` all feed the same batcher.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import ctypes

from OpenGL.GL import (
    GL_CCW, GL_CULL_FACE, glDisable, glEnable, glFrontFace,
)

__all__ = (
    'InstanceGroup',
    'geometry_instance_key',
    'geometry_texture_key',
    'geometry_content_key',
    'geometry_content_instance_key',
    'build_mesh_gpu',
    'group_material_table',
    'build_instance_groups',
    'morton_order',
    'Cluster',
    'build_clusters',
    'cluster_cull',
    'max_materials_per_ubo',
    'GLCapabilities',
    'detect_capabilities',
    'INSTANCE_ATTR_LOC',
    'INSTANCE_OBJECT_ID_LOC',
    'INSTANCE_MATERIAL_LOC',
    'pack_instance_buffer',
    'draw_instanced_mesh',
)

# Per-instance attribute locations (must match pbr.vert). A mat4 occupies four
# consecutive locations (5..8); the packed object id at 9; the material-array
# index at 10.
INSTANCE_ATTR_LOC = 5
INSTANCE_OBJECT_ID_LOC = 9
INSTANCE_MATERIAL_LOC = 10

# std140 MaterialBlock stride in bytes (mirrors pbrpass.MATERIAL_UBO stride); used
# to size a per-instance material array against the driver's UBO limit.
MATERIAL_STRIDE_BYTES = 176


def max_materials_per_ubo(block_size_bytes: int,
                          stride: int = MATERIAL_STRIDE_BYTES) -> int:
    """How many materials fit in one uniform block of ``block_size_bytes``.

    A group whose distinct-material count exceeds this must be chunked into
    several instanced draws (GL 3.3 UBOs cap at GL_MAX_UNIFORM_BLOCK_SIZE, 16 KB
    guaranteed). At least 1, so a caller can always make progress.
    """
    return max(1, int(block_size_bytes) // int(stride))


def geometry_instance_key(path: Any) -> Optional[tuple]:
    """Instance-batch key for a render path, or None if it has no geometry.

    Two records share a batch when they share geometry AND a compatible
    appearance. Identity (``id(...)``) captures the common cases cheaply: VRML
    ``USE``/``DEF`` and glTF shared-mesh nodes reuse one geometry object, and
    loaders share one material/texture instance across the parts that use it.

    The material factors themselves are allowed to differ per instance once the
    material-array path lands (Stage 2); until then, batching on material
    identity keeps every instance in a group visually identical, which is the
    common duplicated-geometry case.
    """
    shape = path[-1]
    geometry = getattr(shape, 'geometry', None)
    if geometry is None:
        return None
    appearance = getattr(shape, 'appearance', None)
    material = getattr(appearance, 'material', None) if appearance is not None else None
    texture = getattr(appearance, 'texture', None) if appearance is not None else None
    return (id(geometry), id(material), id(texture))


def _material_texture_ids(material: Any) -> tuple:
    """Identity tuple of the textures a material references (empty if none).

    Two materials with the same textures (or both untextured) can share one
    instanced draw and differ only by factors -- textures cannot vary per instance
    in GL 3.3 (no bindless), so a differing texture set must split the group.
    """
    if material is None:
        return ()
    # PBRMaterial keeps its texture references in a ``textures`` dict (channel ->
    # texture); an empty dict means untextured, which is the common instanceable
    # case. Sorted so the key is order-independent.
    textures = getattr(material, 'textures', None)
    if isinstance(textures, dict):
        return tuple((channel, id(tex)) for channel, tex in sorted(textures.items())
                     if tex is not None)
    # Fallback for other material types: scan common single-texture attributes,
    # skipping methods (e.g. PBRMaterial.texture is a lookup method, not a node)
    # and unset channels.
    ids: list = []
    for attr in ('baseColorTexture', 'metallicRoughnessTexture', 'normalTexture',
                 'occlusionTexture', 'emissiveTexture'):
        tex = getattr(material, attr, None)
        if tex is not None and not callable(tex):
            ids.append((attr, id(tex)))
    return tuple(ids)


def _material_pass_signature(material: Any) -> tuple:
    """Properties that are pass-level uniforms, not per-instance UBO factors.

    ``alphaMode``, transmission and transparency drive shared uniforms / which
    pass a shape draws in, so they cannot vary within one instanced draw -- two
    materials must agree on them to batch. Null-safe: a material lacking these
    (a plain fake, or a VRML97 Material) yields a constant signature so such
    materials still group together.
    """
    if material is None:
        return (None, False, False)
    am = getattr(material, 'alphaMode', None)
    transmission = float(getattr(material, 'transmission', 0.0) or 0.0) > 0.0
    transparency = float(getattr(material, 'transparency', 0.0) or 0.0) > 0.0
    return (str(am) if am is not None else None, transmission, transparency)


def geometry_texture_key(path: Any) -> Optional[tuple]:
    """Stage 2 batch key: geometry + texture set + pass signature, IGNORING
    material identity.

    Groups shapes that share geometry, textures and pass-level properties but
    differ by material FACTORS (colour, metallic, roughness) into one instanced
    draw; each instance then indexes its own material in the group's material
    array. Returns None when there is no geometry.
    """
    shape = path[-1]
    geometry = getattr(shape, 'geometry', None)
    if geometry is None:
        return None
    appearance = getattr(shape, 'appearance', None)
    material = getattr(appearance, 'material', None) if appearance is not None else None
    texture = getattr(appearance, 'texture', None) if appearance is not None else None
    tex_key = _material_texture_ids(material)
    if not tex_key and texture is not None:
        tex_key = (('appearance_texture', id(texture)),)
    return (id(geometry), tex_key, _material_pass_signature(material))


def _geometry_content_id(geometry: Any) -> Any:
    """A content signature for a mesh: two nodes with identical geometry get the
    same id, so distinct-but-identical geometry can batch (a sphere field of many
    same-radius Sphere nodes, glTF repeated meshes, a primitive authored several
    times). Returns None for geometry with no content signature (falls back to
    node identity).

    A geometry can supply a cheap explicit signature via ``instanceContentKey()``
    (e.g. Sphere -> ('Sphere', radius)); otherwise a mesh with vertex arrays is
    hashed once and cached.
    """
    explicit = getattr(geometry, 'instanceContentKey', None)
    if callable(explicit):
        try:
            key = explicit()
            if key is not None:
                return key
        except Exception:
            pass
    cached = getattr(geometry, '_instance_content_id', None)
    if cached is not None:
        return cached
    positions = getattr(geometry, 'positions', None)
    if positions is None:
        return None
    import hashlib
    h = hashlib.blake2b(digest_size=16)
    for name in ('positions', 'normals', 'texcoords', 'tangents', 'colors', 'indices'):
        arr = getattr(geometry, name, None)
        if arr is not None:
            h.update(name.encode('ascii'))
            h.update(np.ascontiguousarray(arr).tobytes())
    cid = h.hexdigest()
    try:
        geometry._instance_content_id = cid
    except Exception:
        pass
    return cid


def geometry_content_key(path: Any) -> Optional[tuple]:
    """Stage 3 batch key: geometry CONTENT + texture set + pass signature.

    Like :func:`geometry_texture_key` but keys geometry by content hash instead of
    node identity, so two distinct nodes with identical vertex data collapse into
    one instanced draw. Falls back to node identity for geometry without vertex
    arrays. Returns None when there is no geometry.
    """
    shape = path[-1]
    geometry = getattr(shape, 'geometry', None)
    if geometry is None:
        return None
    content = _geometry_content_id(geometry)
    if content is None:
        content = id(geometry)
    appearance = getattr(shape, 'appearance', None)
    material = getattr(appearance, 'material', None) if appearance is not None else None
    texture = getattr(appearance, 'texture', None) if appearance is not None else None
    tex_key = _material_texture_ids(material)
    if not tex_key and texture is not None:
        tex_key = (('appearance_texture', id(texture)),)
    return (content, tex_key, _material_pass_signature(material))


def geometry_content_instance_key(path: Any) -> Optional[tuple]:
    """Content-based key that ALSO splits on material identity.

    For passes that bind a single material per instanced group (the VRML97 lit
    path -- per-instance material factors are PBR-only), so a sphere field batches
    per (geometry-content, material): same-radius atoms sharing one Material node
    collapse into one draw, differently-coloured atoms into their own. Returns None
    when there is no geometry.
    """
    shape = path[-1]
    geometry = getattr(shape, 'geometry', None)
    if geometry is None:
        return None
    content = _geometry_content_id(geometry)
    if content is None:
        content = id(geometry)
    appearance = getattr(shape, 'appearance', None)
    material = getattr(appearance, 'material', None) if appearance is not None else None
    texture = getattr(appearance, 'texture', None) if appearance is not None else None
    return (content, id(material), id(texture))


def build_mesh_gpu(mode: Any, node: Any, positions: Any, normals: Any = None,
                   texcoords: Any = None, indices: Any = None,
                   cache_key: str = 'instance_gpu',
                   depend_fields: tuple = ()) -> Any:
    """Build (and cache on the context) a PBRMesh-style ``_MeshGPU`` from raw arrays.

    Lets any geometry become instanceable by handing over its expanded vertex
    arrays in the shader's attribute layout (separate VBOs at locations
    texcoord=0, normal=1, position=2); the same ``_MeshGPU`` + ``draw_instanced_mesh``
    path then serves Box, Sphere and PBRMesh alike. Cached per node (rebuilt when a
    ``depend_fields`` field changes, e.g. Box.size / Sphere.radius).
    """
    gpu = mode.cache.getData(node, key=cache_key)
    if gpu is not None:
        return gpu
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh, _MeshGPU

    class _ArrayMesh(object):
        __slots__ = ('positions', 'normals', 'texcoords', 'texcoords1',
                     'tangents', 'colors', 'indices')
        positions: np.ndarray
        normals: Optional[np.ndarray]
        texcoords: Optional[np.ndarray]
        texcoords1: Optional[np.ndarray]
        tangents: Optional[np.ndarray]
        colors: Optional[np.ndarray]
        indices: Optional[np.ndarray]

    m = _ArrayMesh()
    m.positions = np.ascontiguousarray(positions, dtype=np.float32)
    m.normals = None if normals is None else np.ascontiguousarray(normals, dtype=np.float32)
    m.texcoords = None if texcoords is None else np.ascontiguousarray(texcoords, dtype=np.float32)
    m.texcoords1 = None      # quadric/IFS geometry has no second UV set
    m.tangents = None
    m.colors = None
    m.indices = None if indices is None else np.ascontiguousarray(indices, dtype=np.uint32).ravel()
    gpu = _MeshGPU(m, pending_deletes=PBRMesh._pending_delete_queue(mode))
    holder = mode.cache.holder(node, gpu, key=cache_key)
    for f in depend_fields:
        try:
            holder.depend(node, f)
        except Exception:
            pass
    return gpu


def set_cull_state(mode: Any, enabled: bool, front_face: int) -> None:
    """Set face culling and winding for the next draw, if they are not already.

    **The memo of what GL currently has belongs to the pass, and this is how it
    is reached.**  A geometry node that wanted a particular winding used to
    write the pass's private attributes from another package: an
    underscore-prefixed protocol with two participants, no owner, and nothing
    to find it by from the pass's own module.

    Re-issued only when it actually changes -- an assembly draws hundreds of
    same-state shapes in a row -- and reset once per pass by
    :func:`reset_cull_state` rather than per draw.
    """
    if getattr(mode, '_cull_front_face', None) != front_face:
        glFrontFace(front_face)
        mode._cull_front_face = front_face
    if getattr(mode, '_cull_enabled', None) != enabled:
        (glEnable if enabled else glDisable)(GL_CULL_FACE)
        mode._cull_enabled = enabled


def reset_cull_state(mode: Any) -> None:
    """Put culling and winding back to the GL defaults after a geometry loop.

    Called once per pass, so a mesh's clockwise winding or disabled culling
    never leaks into the next pass or frame.  Idempotent, and safe when nothing
    set the state at all.
    """
    if getattr(mode, '_cull_front_face', None) not in (None, GL_CCW):
        glFrontFace(GL_CCW)
    if getattr(mode, '_cull_enabled', None) is False:
        glEnable(GL_CULL_FACE)
    mode._cull_front_face = None
    mode._cull_enabled = None


def group_material_table(group: Any) -> tuple[list, list]:
    """Distinct materials of a group + a per-member index into that table.

    Returns (materials, indices): ``materials`` lists the group's distinct
    material objects in first-seen order; ``indices[i]`` is member i's slot in that
    list. This is what the material-array UBO is packed from and what the
    per-instance material-index attribute carries.
    """
    materials: list = []
    slot: dict = {}
    indices: list = []
    for rec in group.members:
        shape = rec[-1][-1]
        appearance = getattr(shape, 'appearance', None)
        material = getattr(appearance, 'material', None) if appearance is not None else None
        k = id(material)
        if k not in slot:
            slot[k] = len(materials)
            materials.append(material)
        indices.append(slot[k])
    return materials, indices


def morton_order(positions: Any) -> list:
    """Indices that sort ``positions`` (Nx3) by 3D Morton (Z-order) code.

    Morton codes interleave the bits of the quantized x/y/z coordinates, so points
    that are close in space get codes that are close in value: sorting by the code
    lays spatially-near instances next to each other, which is what lets
    :func:`build_clusters` cut the field into compact, contiguous clusters. The
    quantization is to a 10-bit grid (1024^3) over the field's bounding box --
    plenty for grouping; it does not affect rendered positions.
    """
    pts = np.asarray(positions, dtype='f')
    n = len(pts)
    if n <= 1:
        return list(range(n))
    lo = pts.min(axis=0)
    span = pts.max(axis=0) - lo
    span[span == 0] = 1.0
    q = np.clip(((pts - lo) / span * 1023.0).astype(np.uint64), 0, 1023)

    def _spread(v: np.ndarray) -> np.ndarray:
        # Spread 10 low bits of v so there are two zero bits between each.
        v = v & 0x3FF
        v = (v | (v << 16)) & 0x030000FF
        v = (v | (v << 8)) & 0x0300F00F
        v = (v | (v << 4)) & 0x030C30C3
        v = (v | (v << 2)) & 0x09249249
        return v

    codes = _spread(q[:, 0]) | (_spread(q[:, 1]) << 1) | (_spread(q[:, 2]) << 2)
    return list(np.argsort(codes, kind='stable'))


class Cluster:
    """A contiguous run of spatially-near instances with a combined world AABB.

    ``indices`` are positions into the caller's instance list; ``aabb_min`` /
    ``aabb_max`` bound those instances' world translations, so one frustum test on
    the AABB can accept or reject the whole run.
    """

    __slots__ = ('indices', 'aabb_min', 'aabb_max')

    def __init__(self, indices: list, aabb_min: np.ndarray,
                 aabb_max: np.ndarray) -> None:
        self.indices = indices
        self.aabb_min = aabb_min
        self.aabb_max = aabb_max


def build_clusters(positions: Any, cluster_size: int = 64) -> list[Cluster]:
    """Partition instance ``positions`` (Nx3) into Morton-ordered clusters.

    Each cluster holds up to ``cluster_size`` spatially-adjacent instances and its
    world-space AABB. Returns a list of :class:`Cluster`. Clustering is the
    build-time half of cluster culling; the per-frame half tests each cluster's
    AABB against the frustum (see :func:`cluster_cull`).
    """
    pts = np.asarray(positions, dtype='f')
    order = morton_order(pts)
    clusters: list[Cluster] = []
    for start in range(0, len(order), cluster_size):
        idx = order[start:start + cluster_size]
        block = pts[idx]
        clusters.append(Cluster(list(idx), block.min(axis=0), block.max(axis=0)))
    return clusters


def cluster_cull(records: list, positions: Any, cluster_visible: Callable,
                 instance_visible: Callable, cluster_size: int = 64) -> list:
    """Return the visible subset of ``records`` using cluster pre-culling.

    ``positions`` are the records' world translations (Nx3). Instances are grouped
    into spatial clusters; for each cluster, ``cluster_visible(aabb_min, aabb_max)``
    is tested once. A cluster that is wholly outside the frustum culls all its
    members with no per-instance work -- the win for scenes where whole regions are
    off-screen. For a cluster that might be visible, each member falls back to the
    exact ``instance_visible(record)`` test, so the result is identical to testing
    every instance directly, just cheaper. Order of the surviving records is
    preserved.
    """
    clusters = build_clusters(positions, cluster_size=cluster_size)
    keep = [False] * len(records)
    for c in clusters:
        if not cluster_visible(c.aabb_min, c.aabb_max):
            continue
        for i in c.indices:
            if instance_visible(records[i]):
                keep[i] = True
    return [rec for i, rec in enumerate(records) if keep[i]]


class InstanceGroup:
    """A set of render records that draw together as one instanced call.

    Attributes:
        key       -- the shared instance key (see ``geometry_instance_key``).
        geometry  -- the shared geometry node (drawn once, instanced N times).
        appearance-- a representative appearance (material/texture) for the group.
        members   -- the render records, in scene order; one instance each.
    """

    __slots__ = ('key', 'geometry', 'appearance', 'members')

    def __init__(self, key: Any, geometry: Any, appearance: Any,
                 members: list) -> None:
        self.key = key
        self.geometry = geometry
        self.appearance = appearance
        self.members = members

    def __len__(self) -> int:
        return len(self.members)

    def __repr__(self) -> str:
        return 'InstanceGroup(%d instances of %r)' % (len(self.members), self.geometry)


def _winding_sign(mv: Any) -> int:
    """Sign of a modelview's upper-3x3 determinant (-1 flips triangle winding).

    A direct 3x3 solve (not LAPACK), tolerant of a numpy array or a nested list.
    """
    a = mv.tolist() if hasattr(mv, 'tolist') else mv
    try:
        d = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
             - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
             + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    except (TypeError, IndexError):
        return 1
    return -1 if d < 0 else 1


def build_instance_groups(
    records: List[tuple],
    min_instances: int = 2,
    key: Callable = geometry_instance_key,
    instanceable: Optional[Callable] = None,
) -> Tuple[List[InstanceGroup], List[tuple]]:
    """Partition render records into instanced groups and leftover singles.

    Args:
        records: (sortKey, mvmatrix, tmatrix, bvolume, path) tuples -- the opaque
            render set. Order is preserved: groups appear in first-seen order and
            each group's members keep scene order.
        min_instances: a batch needs at least this many members to be worth an
            instanced draw (instancing has fixed per-batch setup cost); smaller
            batches fall through to singles.
        key: record-path -> hashable key (or None to never batch that record).
        instanceable: predicate(path) -> bool; records whose geometry cannot be
            drawn instanced are always singles. Defaults to "everything with a
            key is instanceable".

    Returns:
        (groups, singles). Every input record appears exactly once across the two.
    """
    buckets: "Dict[Any, List[tuple]]" = {}
    order: List[Any] = []
    singles: List[tuple] = []

    for record in records:
        path = record[-1]
        k = key(path)
        if k is None or (instanceable is not None and not instanceable(path)):
            singles.append(record)
            continue
        # A batch is drawn with ONE front-face winding, so instances of opposite
        # modelview determinant (mirror / negative scale) cannot share a group --
        # the negatively-scaled ones would mis-cull and light inside-out
        # (NegativeScaleTest). Fold the winding sign into the bucket key so each
        # group is uniform, and _drawInstanceGroup's per-group _apply_draw_state
        # (from members[0]) then sets the correct winding for all of it.
        k = (k, _winding_sign(record[1]))
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(record)

    groups: List[InstanceGroup] = []
    for k in order:
        members = buckets[k]
        if len(members) < min_instances:
            singles.extend(members)
            continue
        shape = members[0][-1][-1]
        groups.append(InstanceGroup(
            key=k,
            geometry=shape.geometry,
            appearance=getattr(shape, 'appearance', None),
            members=members,
        ))
    return groups, singles


# --------------------------------------------------------------------------- #
# GL capability detection: pick the conditional draw path the driver supports.  #
# --------------------------------------------------------------------------- #

class GLCapabilities(object):
    """What the current GL context can do for instancing.

    Baseline instancing (``glDrawElementsInstanced`` + ``glVertexAttribDivisor``)
    is core since GL 3.1, so it is assumed present. The remaining flags gate
    optional faster paths added in later stages:

        ssbo               -- GL 4.3 shader-storage buffers: an unbounded
                              per-instance material array (no UBO 16 KB cap).
        multi_draw_indirect-- GL 4.3: draw many groups in one call.
        bindless_texture   -- ARB_bindless_texture: per-instance *textures*, so
                              instances can differ by texture set, not just
                              material factors -- effectively per-instance
                              appearance without a program switch.
    """

    __slots__ = ('version', 'max_uniform_block_size', 'ssbo',
                 'multi_draw_indirect', 'bindless_texture', 'extensions')

    def __init__(self, version: tuple = (3, 3),
                 max_uniform_block_size: int = 16384,
                 ssbo: bool = False, multi_draw_indirect: bool = False,
                 bindless_texture: bool = False,
                 extensions: Any = ()) -> None:
        self.version = version
        self.max_uniform_block_size = max_uniform_block_size
        self.ssbo = ssbo
        self.multi_draw_indirect = multi_draw_indirect
        self.bindless_texture = bindless_texture
        self.extensions = frozenset(extensions)

    def max_materials(self) -> int:
        """Per-instance material array capacity via a UBO (UBO-path chunk size)."""
        return max_materials_per_ubo(self.max_uniform_block_size)

    def __repr__(self) -> str:
        return ('GLCapabilities(version=%r ubo=%d ssbo=%r mdi=%r bindless=%r)'
                % (self.version, self.max_uniform_block_size, self.ssbo,
                   self.multi_draw_indirect, self.bindless_texture))


_CAPS_CACHE: Optional[GLCapabilities] = None


def detect_capabilities(force: bool = False) -> GLCapabilities:
    """Query the current GL context once and cache the result.

    Requires a current context. Any failure degrades to the safe 3.3 baseline
    rather than raising, so a quirky driver never breaks rendering.
    """
    global _CAPS_CACHE
    if _CAPS_CACHE is not None and not force:
        return _CAPS_CACHE
    try:
        from OpenGL.GL import (
            glGetIntegerv, GL_MAX_UNIFORM_BLOCK_SIZE,
            GL_MAJOR_VERSION, GL_MINOR_VERSION, GL_NUM_EXTENSIONS,
            GL_EXTENSIONS,
        )
        try:
            major = int(glGetIntegerv(GL_MAJOR_VERSION))
            minor = int(glGetIntegerv(GL_MINOR_VERSION))
        except Exception:
            major, minor = 3, 3
        try:
            block = int(glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE))
        except Exception:
            block = 16384

        exts = set()
        try:
            from OpenGL.GL import glGetStringi
            n = int(glGetIntegerv(GL_NUM_EXTENSIONS))
            for i in range(n):
                s = glGetStringi(GL_EXTENSIONS, i)
                if s:
                    exts.add(s.decode('latin-1') if isinstance(s, bytes) else str(s))
        except Exception:
            pass

        ver = (major, minor)
        ge43 = ver >= (4, 3)
        caps = GLCapabilities(
            version=ver,
            max_uniform_block_size=block,
            ssbo=ge43 or 'GL_ARB_shader_storage_buffer_object' in exts,
            multi_draw_indirect=ge43 or 'GL_ARB_multi_draw_indirect' in exts,
            bindless_texture='GL_ARB_bindless_texture' in exts,
            extensions=exts,
        )
    except Exception:
        caps = GLCapabilities()
    _CAPS_CACHE = caps
    return caps


# --------------------------------------------------------------------------- #
# GL instanced draw for a PBRMesh's cached VAO + a per-instance data buffer.    #
# --------------------------------------------------------------------------- #

_INSTANCE_DTYPE: Optional[np.dtype] = None


def _instance_dtype() -> np.dtype:
    """One instance: mat4 modelview (16 f32) + object id (u32) + material idx (u32)."""
    global _INSTANCE_DTYPE
    if _INSTANCE_DTYPE is None:
        _INSTANCE_DTYPE = np.dtype([('mv', '<f4', 16), ('oid', '<u4'), ('mat', '<u4')])
    return _INSTANCE_DTYPE


def pack_instance_buffer(modelviews: Any, object_ids: Any,
                         material_indices: Any = None) -> np.ndarray:
    """Pack per-instance modelviews + object ids + material indices.

    The modelview is stored row-major (as OpenGLContext keeps it); read straight
    into the vertex shader's four mat4 columns it reproduces the GL matrix the
    uniform path uploads with GL_FALSE (see pbr.vert). ``material_indices`` default
    to 0 (single-material group). Returns a numpy structured array whose
    ``.itemsize`` is the vertex-attribute stride.
    """
    n = len(modelviews)
    arr = np.empty(n, dtype=_instance_dtype())
    # One reshape of the whole (N,4,4) / list-of-(4,4) batch into (N,16) rather
    # than a per-instance ravel loop (the depth pass packs a fresh buffer per
    # cascade, so this ran on every group every frame).
    if n:
        arr['mv'][:] = np.asarray(modelviews, dtype='<f4').reshape(n, 16)
    arr['oid'][:] = np.asarray(object_ids, dtype='<u4')
    if material_indices is None:
        arr['mat'][:] = 0
    else:
        arr['mat'][:] = np.asarray(material_indices, dtype='<u4')
    return arr


def _build_instance_vao(gpu: Any, arr: np.ndarray, stride: int) -> tuple:
    """Build the persistent instanced-draw VAO + instance VBO for ``gpu`` once.

    The VAO records the mesh's static attribute VBOs (0..4), its element buffer,
    and the per-instance divisor attributes (model matrix 5..8, object id 9,
    material index 10) pointing at a persistent ``vbo.VBO`` seeded with ``arr``.
    Cached on the gpu object so every later frame is just: bind the VAO, re-upload
    the instance VBO, draw -- no VAO/VBO gen or delete. The instance VBO is a
    ``vbo.VBO`` (self-finalizing like the static ones); the VAO id is reclaimed by
    :class:`~OpenGLContext.scenegraph.pbrmesh._MeshGPU` when the gpu is collected.
    """
    from OpenGL.GL import (
        GL_FLOAT, GL_FALSE, GL_UNSIGNED_INT,
        glGenVertexArrays, glBindVertexArray,
        glEnableVertexAttribArray, glVertexAttribPointer, glVertexAttribIPointer,
        glVertexAttribDivisor,
    )
    from OpenGL.arrays import vbo
    inst_vbo = vbo.VBO(arr, usage='GL_DYNAMIC_DRAW')
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    # Static per-vertex attributes (position/normal/texcoord/tangent/color).
    for buf, loc, size in gpu.attr_layout:
        buf.bind()
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, size, GL_FLOAT, GL_FALSE, 0, None)
    if gpu.idx_vbo is not None:
        gpu.idx_vbo.bind()
    inst_vbo.bind()   # creates the GL buffer and uploads the seed data
    # mat4 modelview across four vec4 columns, each divisor-1.
    for col in range(4):
        loc = INSTANCE_ATTR_LOC + col
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, 4, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(col * 16))
        glVertexAttribDivisor(loc, 1)
    # Packed object id + material-array index (integer attributes at 64, 68).
    glEnableVertexAttribArray(INSTANCE_OBJECT_ID_LOC)
    glVertexAttribIPointer(INSTANCE_OBJECT_ID_LOC, 1, GL_UNSIGNED_INT, stride,
                           ctypes.c_void_p(64))
    glVertexAttribDivisor(INSTANCE_OBJECT_ID_LOC, 1)
    glEnableVertexAttribArray(INSTANCE_MATERIAL_LOC)
    glVertexAttribIPointer(INSTANCE_MATERIAL_LOC, 1, GL_UNSIGNED_INT, stride,
                           ctypes.c_void_p(68))
    glVertexAttribDivisor(INSTANCE_MATERIAL_LOC, 1)
    glBindVertexArray(0)
    gpu._instance_vao = vao
    gpu._instance_vbo = inst_vbo
    return vao, inst_vbo


def draw_instanced_mesh(gpu: Any, modelviews: Any, object_ids: Any,
                        material_indices: Any = None) -> int:
    """Draw ``gpu`` (a PBRMesh ``_MeshGPU``) once per instance in one GL call.

    Uses a VAO + per-instance VBO cached on ``gpu`` (built once by
    :func:`_build_instance_vao`, reused every frame): the per-instance data is
    re-uploaded into the persistent VBO and the draw is issued -- no VAO/VBO churn.
    The instance modelviews are eye-space (view*model), so the buffer is re-uploaded
    each frame even for a static scene; cluster culling (see the plan) is what lets
    a cached, spatially-sorted buffer skip the re-upload. Returns the count drawn.
    """
    from OpenGL.GL import (
        GL_TRIANGLES, GL_UNSIGNED_INT,
        glBindVertexArray, glDrawElementsInstanced, glDrawArraysInstanced,
    )
    n = len(modelviews)
    if n == 0:
        return 0
    arr = pack_instance_buffer(modelviews, object_ids, material_indices)
    stride = arr.dtype.itemsize

    vao = getattr(gpu, '_instance_vao', None)
    if vao is None:
        vao, inst_vbo = _build_instance_vao(gpu, arr, stride)
        glBindVertexArray(vao)
    else:
        inst_vbo = gpu._instance_vbo
        inst_vbo.set_array(arr)
        glBindVertexArray(vao)
        inst_vbo.bind()   # re-upload into the persistent buffer the VAO references
    draw_mode = int(getattr(gpu, 'draw_mode', GL_TRIANGLES))
    try:
        if gpu.indexed:
            glDrawElementsInstanced(draw_mode, gpu.count, GL_UNSIGNED_INT,
                                    None, n)
        else:
            glDrawArraysInstanced(draw_mode, 0, gpu.count, n)
    finally:
        glBindVertexArray(0)
    return n
