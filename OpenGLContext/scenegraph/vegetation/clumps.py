"""GPU-instanced real-geometry grass clumps (near-field LOD).

Where :mod:`billboards` draws camera-facing quads, this draws an actual authored
*clump mesh* — dozens of individual blades — instanced at many (position, yaw,
scale). Real geometry means blades occlude objects correctly at grazing angles
(the "blades in front of the log" look) instead of pivoting to face the camera.
It shares the ``veg_mesh`` shaders with :mod:`nearmesh` (per-instance yaw+scale,
single alpha-cutout pass, depth-correct), so it slots into the same near end of a
distance-LOD scheme with billboard grass taking over further out.

Per-instance data is replaced each frame with :meth:`update_instances` for a
camera-following field, exactly like :class:`InstancedBillboards`.
"""
import io, json, struct, ctypes
import numpy as np
from PIL import Image
from OpenGL.GL import *
from OpenGLContext.scenegraph.instancedgl import (
    load_program, texture_rgba, delete_gl, setup_instance_attribs, InstanceBuffer)
from OpenGLContext.scenegraph.vegetation.base import InstancedVegBase, _BIG

_CT = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
_NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def _decimate_ribbons(P, N, UV, idx, length_samples):
    """Thin blade ribbons along their length, keeping ``length_samples`` cross-rings.

    A clump is dozens of separate blade ribbons; each is a strip of cross-rings
    running root (UV.v=0) to tip (UV.v=1). Grass reads fine with 3-4 length segments,
    so the source's dozen-plus rings per blade are wasted triangles. We keep an evenly
    spaced subset of rings (always root and tip) and *collapse* each dropped ring onto
    the nearest kept one — an edge collapse that only removes triangles, never invents
    topology, so the result is always a valid mesh with the blade outline preserved.
    """
    tris = idx.reshape(-1, 3)
    parent = np.arange(len(P))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for t in tris:                                   # union blades = connected components
        ra = find(t[0])
        for x in t[1:]:
            parent[find(int(x))] = ra
    groups = {}
    for v in range(len(P)):
        groups.setdefault(find(v), []).append(v)

    remap = np.arange(len(P))
    for verts in groups.values():
        verts = np.asarray(verts)
        vv = UV[verts, 1]
        order = np.argsort(vv); sv = verts[order]; svv = vv[order]
        rings = []; cur = [sv[0]]                     # cluster verts into rings by UV.v gaps
        for k in range(1, len(sv)):
            if svv[k] - svv[k - 1] > 0.02:
                rings.append(np.asarray(cur)); cur = [sv[k]]
            else:
                cur.append(sv[k])
        rings.append(np.asarray(cur))
        nr = len(rings)
        if nr <= length_samples:
            continue
        keep = set(np.linspace(0, nr - 1, length_samples).round().astype(int).tolist())
        keep |= {0, nr - 1}
        keep_sorted = sorted(keep)
        by_u = [r[np.argsort(UV[r, 0])] for r in rings]   # left/centre/right order within a ring
        for ri in range(nr):
            if ri in keep:
                continue
            kj = min(keep_sorted, key=lambda a: abs(a - ri))
            src, dst = by_u[ri], by_u[kj]
            for i, w in enumerate(src):
                remap[w] = dst[min(i, len(dst) - 1)]

    nt = remap[tris]
    good = (nt[:, 0] != nt[:, 1]) & (nt[:, 1] != nt[:, 2]) & (nt[:, 0] != nt[:, 2])
    nt = nt[good]
    used = np.unique(nt)
    old2new = np.empty(len(P), int); old2new[used] = np.arange(len(used))
    return (P[used], N[used], UV[used], old2new[nt].ravel().astype(np.uint32))


def load_clump_glb(path, normalize_height=True, length_samples=None):
    """Load a single-mesh ``.glb`` clump into ``(P, N, UV, idx, tex_image)``.

    Extracts the first mesh's POSITION/NORMAL/TEXCOORD_0/indices and the first
    embedded image (returned as a decoded ``PIL.Image``, so nothing is written
    beside the asset). With
    ``normalize_height`` the mesh is rescaled so it is exactly 1.0 unit tall with
    its base at ``y=0``, so a per-instance scale reads directly as blade height in
    world units. ``length_samples`` (int) decimates each blade ribbon to that many
    cross-rings for LOD headroom (see :func:`_decimate_ribbons`); ``None`` keeps the
    source tessellation.
    """
    with open(path, 'rb') as fh:
        d = fh.read()
    _, _, ln = struct.unpack('<III', d[:12]); off = 12; chunks = []
    while off < ln:
        clen, ctype = struct.unpack('<II', d[off:off + 8]); off += 8
        chunks.append((ctype, d[off:off + clen])); off += clen
    g = json.loads(chunks[0][1]); bd = chunks[1][1]
    acc, bv = g['accessors'], g['bufferViews']

    def read(i):
        a = acc[i]; v = bv[a['bufferView']]
        o = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        arr = np.frombuffer(bd, _CT[a['componentType']], a['count'] * _NC[a['type']], o)
        return arr.reshape(a['count'], _NC[a['type']])

    pr = g['meshes'][0]['primitives'][0]
    P = read(pr['attributes']['POSITION']).astype(np.float32)
    N = read(pr['attributes']['NORMAL']).astype(np.float32)
    UV = read(pr['attributes']['TEXCOORD_0']).astype(np.float32)
    idx = read(pr['indices']).ravel().astype(np.uint32)
    if length_samples is not None:
        P, N, UV, idx = _decimate_ribbons(P, N, UV, idx, int(length_samples))
    img = g['images'][0]; iv = bv[img['bufferView']]; io0 = iv.get('byteOffset', 0)
    raw = bd[io0:io0 + iv['byteLength']]
    tex_image = Image.open(io.BytesIO(raw)).convert("RGBA")
    if normalize_height:
        P = P.copy(); P[:, 1] -= P[:, 1].min()
        h = P[:, 1].max() or 1.0; P /= h
    return P, N, UV, idx, tex_image


class InstancedClumps(InstancedVegBase):
    """Camera-following instanced grass-clump meshes.

    :param P, N, UV: (V,3)/(V,3)/(V,2) clump mesh arrays (see :func:`load_clump_glb`).
    :param idx: (F*3,) triangle indices.
    :param texture: RGBA blade texture (alpha-cutout at 0.33) as a path or a
        decoded ``PIL.Image`` (see :func:`load_clump_glb`).
    :param sun: world-space sun direction (matches the terrain/tree sun).
    :param bounds: node AABB, kept large so a follow-field is not culled as a whole.
    """
    def __init__(self, P, N, UV, idx, texture, sun=(-0.5, -1.0, -0.35),
                 fade_start=1.0e9, fade_end=1.0e9, bounds=_BIG):
        super(InstancedClumps, self).__init__()
        self.P = np.ascontiguousarray(P, np.float32)
        self.N = np.ascontiguousarray(N, np.float32)
        self.UV = np.ascontiguousarray(UV, np.float32)
        self.idx = np.ascontiguousarray(idx, np.uint32)
        self.texture_src = texture
        self.sun = np.asarray(sun, 'd'); self.sun /= np.linalg.norm(self.sun)
        #: eye-distance window over which clumps dither-dissolve out (billboards take
        #: over). Defaults far away = no fade; set to match the scatter radius.
        self.fade_start = float(fade_start); self.fade_end = float(fade_end)
        self.bounds = bounds
        self._gl = None; self._pending = None; self._disabled = False

    def update_instances(self, positions, yaws, scales):
        """Stage a new instance set ``(x,y,z, yaw, scale)`` for the next render."""
        p = np.asarray(positions, np.float32); y = np.asarray(yaws, np.float32)
        s = np.asarray(scales, np.float32)
        self._pending = np.concatenate([p, y[:, None], s[:, None]], 1).astype(np.float32)

    def _init_gl(self):
        self._prog = load_program("veg_mesh.vert", "veg_clump.frag")
        self._tex = texture_rgba(self.texture_src, clamp=False)
        mesh = np.concatenate([self.P, self.N, self.UV], 1).astype(np.float32)
        self._vao = glGenVertexArrays(1); glBindVertexArray(self._vao)
        self._mvb = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, self._mvb)
        glBufferData(GL_ARRAY_BUFFER, mesh.nbytes, mesh, GL_STATIC_DRAW)
        for loc, sz, o in ((0, 3, 0), (1, 3, 12), (2, 2, 24)):
            glVertexAttribPointer(loc, sz, GL_FLOAT, GL_FALSE, 32, ctypes.c_void_p(o))
            glEnableVertexAttribArray(loc)
        self._ib = glGenBuffers(1); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ib)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, self.idx.nbytes, self.idx, GL_STATIC_DRAW)
        self._ibuf = InstanceBuffer(); glBindBuffer(GL_ARRAY_BUFFER, self._ibuf.id)
        setup_instance_attribs(3, 4)
        glBindVertexArray(0)
        self.U = {x: glGetUniformLocation(self._prog, x) for x in
                  ("uModelView", "uProjection", "atlas", "sunDirEye", "sunColor",
                   "skyAmbient", "groundAmbient", "fogDensity", "fogColor",
                   "uFadeStart", "uFadeEnd", "uUpEye")}
        self._commit_constants()
        self._gl = self._prog

    def _upload_constants(self):
        U = self.U
        glUniform1i(U["atlas"], 0); glUniform3f(U["sunColor"], 1.25, 1.18, 1.02)
        glUniform3f(U["skyAmbient"], 0.5, 0.58, 0.66); glUniform3f(U["groundAmbient"], 0.14, 0.16, 0.11)
        glUniform1f(U["fogDensity"], 0.00016); glUniform3f(U["fogColor"], 0.46, 0.58, 0.76)
        glUniform1f(U["uFadeStart"], self.fade_start); glUniform1f(U["uFadeEnd"], self.fade_end)

    def dispose(self):
        """Free this node's GL objects (VAO, buffers, texture, program). GL thread."""
        if not self._gl:
            return
        delete_gl(vaos=[self._vao], buffers=[self._mvb, self._ib, self._ibuf.id],
                  textures=[self._tex], programs=[self._prog])
        self._gl = None

    def _stream(self):
        if self._pending is not None:
            self._ibuf.upload(self._pending); self._pending = None
        return self._ibuf.count > 0

    def _draw(self, mode):
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, self._tex)
        glEnable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glDisable(GL_BLEND); glDepthMask(GL_TRUE)
        glBindVertexArray(self._vao)
        glDrawElementsInstanced(GL_TRIANGLES, len(self.idx), GL_UNSIGNED_INT, None, self._ibuf.count)
        glBindVertexArray(0)
