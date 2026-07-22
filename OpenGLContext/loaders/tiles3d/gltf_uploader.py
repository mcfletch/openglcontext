"""glTF tile loading and mounting for the terrain runtime.

`file_tile_loader` runs on a worker thread: it reads a tile's glTF file and parses it
into a scenegraph subtree (numpy-backed; no GL calls — VBOs are built lazily at first
render on the GL thread), returning the parsed scene and the on-disk byte size used
for the memory budget. `GLTileUploader.upload` runs on the GL thread and mounts the
parsed subtree as a drawable node; `release` calls the drawable's `dispose`, which
deletes its GL buffers and textures deterministically instead of leaving them to the
garbage collector (so real VRAM tracks the accounted budget under a tight cap).

Deterministic GL deletion needs a current context: the runtime evicts (and so
releases) inside its per-frame `update` on the GL thread, where one is current. If no
context is current, `dispose` cannot touch GL and falls back to GC reclamation, logging
once — it never leaks silently.

Our sample/bake tiles carry world-space coordinates with an identity tile transform,
so no runtime matrix is applied; non-identity tile transforms are a bake-time concern
(§7).
"""
import logging
import struct

import numpy as np

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.transform import MatrixTransform

log = logging.getLogger(__name__)


def _strip_b3dm(data):
    """Return the embedded glTF/GLB from a b3dm (Batched 3D Model) tile.

    b3dm wraps a GLB behind a 28-byte header plus a feature table and batch table;
    the glTF renderer only needs the GLB, so skip those. Non-b3dm data passes through.
    """
    if data[:4] != b"b3dm":
        return data
    (version, byte_length, ft_json, ft_bin,
     bt_json, bt_bin) = struct.unpack_from("<6I", data, 4)
    offset = 28 + ft_json + ft_bin + bt_json + bt_bin
    return data[offset:]


class _CombinedScene:
    """One drawable subtree for a tile that carries several contents (1.1).

    Wraps each parsed content's group under a shared `Group` and exposes the same
    `group`/`center`/`radius` a single `GLTFScene` does, so the uploader and the
    viewer's auto-framing treat one- and many-content tiles identically.
    """

    def __init__(self, scenes):
        self.group = Group(children=[s.group for s in scenes])
        centers = np.array([np.asarray(s.center, "d") for s in scenes])
        self.center = centers.mean(axis=0)
        self.radius = max(
            float(np.linalg.norm(np.asarray(s.center, "d") - self.center)
                  + (s.radius or 0.0))
            for s in scenes)


def make_tile_loader(cache_dir=None):
    """A tile loader that reads content from local paths or http(s) URLs.

    `cache_dir` is where remote tile payloads are cached (default: the per-user cache
    dir). Returns a `loader_fn(tile) -> (scene, nbytes)` for `TilesetRuntime`.
    """
    def load(tile):
        scenes = []
        nbytes = 0
        for uri in tile.content_uris:
            data = fetch.read_bytes(uri, cache_dir=cache_dir)
            nbytes += len(data)
            scenes.append(gltf.load_gltf(_strip_b3dm(data)))
        scene = scenes[0] if len(scenes) == 1 else _CombinedScene(scenes)
        return scene, nbytes
    return load


# Default loader: local files (and remote, cached under the per-user cache dir). Runs
# on worker threads; no GL calls here.
file_tile_loader = make_tile_loader()


def _drawable_shapes(root):
    """Yield the Shape-like nodes (those with a `geometry`) in a drawable subtree.

    Depth-first and cycle-safe, so a malformed subtree can't loop forever.
    """
    stack = [root]
    seen = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if getattr(node, 'geometry', None) is not None:
            yield node
        for child in (getattr(node, 'children', None) or ()):
            stack.append(child)


def _mesh_vbos(gpu):
    """The distinct vertex/index/instance VBOs a `_MeshGPU` holds."""
    bufs = {}
    for buf in (getattr(gpu, 'idx_vbo', None), getattr(gpu, '_instance_vbo', None)):
        if buf is not None:
            bufs[id(buf)] = buf
    for entry in getattr(gpu, 'attr_layout', None) or ():
        buf = entry[0]
        if buf is not None:
            bufs[id(buf)] = buf
    for buf in (getattr(gpu, 'dyn', None) or {}).values():
        if buf is not None:
            bufs[id(buf)] = buf
    return list(bufs.values())


def _dispose_mesh_gpu(cache, geometry):
    """Delete the per-context VAO/VBOs cached for `geometry`, then drop the entry.

    The mesh's GL resources hang off the context cache keyed on the node; deleting
    them here (rather than waiting for the node to be collected) is what keeps real
    VRAM in step with the residency budget.
    """
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    key = PBRMesh._GPU_CACHE_KEY
    gpu = cache.getData(geometry, key=key)
    if gpu is None:
        return
    try:
        gpu.release()          # deletes the VAO(s)
    except Exception:
        pass
    for buf in _mesh_vbos(gpu):
        try:
            buf.delete()       # deletes the GL buffer now, not on GC
        except Exception:
            pass
    holder = cache.getHolder(geometry, key=key)
    if holder is not None:
        holder()               # de-register so the freed GPU handle is never reused


def _dispose_material_textures(material, context):
    """Delete this context's GL textures for a material's PBR texture maps.

    A tile's `PBRTexture` maps are built from its own images and cached per context;
    they are not shared with other tiles, so deleting them on eviction frees texture
    VRAM without disturbing anything still resident.
    """
    from OpenGL.GL import glDeleteTextures
    ctx_key = id(context)
    for pbr_tex in (getattr(material, 'textures', None) or {}).values():
        per_context = getattr(pbr_tex, '_per_context', None)
        if not per_context:
            continue
        tex = per_context.pop(ctx_key, None)
        tid = getattr(tex, 'texture', None)
        if not tid:
            continue
        try:
            glDeleteTextures([tid])
        except Exception:
            pass
        tex.texture = 0        # already-freed guard for any later cleanup


_warned_no_context = False


def _warn_no_context_once():
    global _warned_no_context
    if not _warned_no_context:
        _warned_no_context = True
        log.warning("Tile GL resources cannot be freed deterministically: no GL "
                    "context is current at release; falling back to GC reclamation.")


def _make_dispose(drawable):
    """Build the drawable's `dispose`: delete its GL buffers/textures, once.

    Idempotent (a second call is a no-op) and guarded against there being no current
    context and against resources that were never uploaded or are already freed.
    """
    state = {'done': False}

    def dispose():
        if state['done']:
            return
        from OpenGLContext.context import getCurrentContext
        context = getCurrentContext()
        cache = getattr(context, 'cache', None)
        if context is None or cache is None:
            _warn_no_context_once()
            return
        state['done'] = True
        seen_materials = set()
        for shape in _drawable_shapes(drawable):
            geometry = shape.geometry
            _dispose_mesh_gpu(cache, geometry)
            for material in (getattr(geometry, 'material', None),
                             getattr(getattr(shape, 'appearance', None),
                                     'material', None)):
                if material is not None and id(material) not in seen_materials:
                    seen_materials.add(id(material))
                    _dispose_material_textures(material, context)

    return dispose


class GLTileUploader:
    """Mounts parsed tile scenes as drawable scenegraph nodes."""

    def upload(self, tile, payload):
        scene, nbytes = payload
        m = tile.world_transform
        if np.allclose(m, np.identity(4)):
            drawable = scene.group
        else:
            # world_transform is column-vector (M·p); MatrixTransform is row-vector (p·M).
            drawable = MatrixTransform(localMatrix=m.T, children=[scene.group])
        drawable.dispose = _make_dispose(drawable)
        return drawable, nbytes

    def release(self, drawable):
        dispose = getattr(drawable, 'dispose', None)
        if dispose is not None:
            dispose()
