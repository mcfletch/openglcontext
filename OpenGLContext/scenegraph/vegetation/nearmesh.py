"""GPU-instanced near-mesh vegetation LOD.

Draws the real tree *meshes* used close to the camera, as the high-detail end of a
distance LOD scheme (the far end being impostor :mod:`billboards`). It is generic
over species: each species is an ``.npz`` mesh with an opaque part (bark/trunk) and
a foliage part, each with its own texture. :meth:`update` filters the full tree set
to those within a radius of the camera and re-uploads the per-species instance
buffers, so only nearby trees are drawn as meshes.

All parts render in a single alpha-CUTOUT pass with depth writes on (no blending),
so every family — including alpha-MASK conifer branches — writes depth and occludes
correctly, with no foliage texture bleeding across trunks.
"""
import ctypes
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CULL_FACE, GL_DEPTH_TEST, GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE, GL_FLOAT, GL_STATIC_DRAW, GL_TEXTURE0, GL_TEXTURE_2D, GL_TRIANGLES,
    GL_TRUE, GL_UNSIGNED_INT, glActiveTexture, glBindBuffer, glBindTexture,
    glBindVertexArray, glBufferData, glDepthMask, glDisable, glDrawElementsInstanced,
    glEnable, glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays,
    glGetUniformLocation, glUniform1f, glUniform1i, glUniform3f, glVertexAttribPointer,
)
from OpenGLContext.scenegraph.instancedgl import (
    load_program, texture_rgba, delete_gl, setup_instance_attribs, InstanceBuffer)
from OpenGLContext.scenegraph.vegetation.base import (
    InstancedVegBase, _BIG, LOD_NEAR, LOD_FAR)
from OpenGLContext.scenegraph.terrain.splat import DEFAULT_SUN


class InstancedMeshLOD(InstancedVegBase):
    """Camera-following instanced tree meshes.

    :param all_pos: (N, 3) world positions of every tree.
    :param all_yaw: (N,) yaw radians per tree.
    :param all_scale: (N,) height scale per tree (world units).
    :param species: list of per-species dicts, each::

            dict(npz=<path to mesh .npz>,
                 o_keys=(P, N, U, I), o_tex=<opaque texture path>,
                 b_keys=(P, N, U, I), b_tex=<foliage texture path>)

        where the key tuples name the arrays in the npz for that part's
        positions/normals/uvs/indices.
    :param species_id: optional (N,) int assigning each tree to a species index;
        defaults to round-robin. Set before the first :meth:`update`.
    """
    def __init__(self, all_pos: np.ndarray, all_yaw: np.ndarray, all_scale: np.ndarray,
                 species: "list[dict[str, Any]]",
                 sun: "tuple[float, float, float]" = DEFAULT_SUN,
                 species_id: Optional[np.ndarray] = None,
                 bounds: "tuple[float, float, float]" = _BIG) -> None:
        super(InstancedMeshLOD, self).__init__()
        self.all_pos = np.asarray(all_pos, np.float32)
        self.all_yaw = np.asarray(all_yaw, np.float32)
        self.all_scale = np.asarray(all_scale, np.float32)
        n = max(1, len(species))
        if species_id is None:
            species_id = np.arange(len(self.all_pos)) % n
        self.all_sp = np.asarray(species_id, int)
        self.species = species
        self.sun = np.asarray(sun, 'd')
        self.sun /= np.linalg.norm(self.sun)
        self.bounds = bounds
        self._gl: Any = None
        self._pending: "Optional[dict[int, np.ndarray]]" = None
        self._disabled = False

    def update(self, cx: float, cz: float, radius: float = 42.0) -> None:
        """Select trees within ``radius`` of ``(cx, cz)`` and stage their instance data."""
        d2 = (self.all_pos[:, 0] - cx) ** 2 + (self.all_pos[:, 2] - cz) ** 2
        near = d2 < radius * radius
        self._pending = {
            s: np.concatenate([self.all_pos[near & (self.all_sp == s)],
                               self.all_yaw[near & (self.all_sp == s), None],
                               self.all_scale[near & (self.all_sp == s), None]], 1).astype(np.float32)
            for s in range(len(self.species))}

    def _mkvao(self, P: np.ndarray, N: np.ndarray, U: np.ndarray, I: np.ndarray,
               ibuf: InstanceBuffer) -> "tuple[Any, int]":
        mesh = np.concatenate([P, N, U], 1).astype(np.float32)
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)
        mvb = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, mvb)
        glBufferData(GL_ARRAY_BUFFER, mesh.nbytes, mesh, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 32, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 32, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, 32, ctypes.c_void_p(24))
        glEnableVertexAttribArray(2)
        idx = I.astype(np.uint32)
        ib = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, ibuf.id)
        setup_instance_attribs(3, 4)
        glBindVertexArray(0)
        self._vaos.append(vao)
        self._buffers += [mvb, ib]
        return vao, len(idx)

    def _init_gl(self) -> None:
        self._prog = load_program("veg_mesh.vert", "veg_mesh.frag")
        # Retain every generated handle so dispose() can free it -- the mesh/index
        # VBOs would otherwise be unreachable the moment _mkvao returns.
        self._vaos: "list[Any]" = []
        self._buffers: "list[Any]" = []
        self._textures: "list[Any]" = []
        tc: "dict[str, Any]" = {}

        def tex(path: str) -> Any:
            if path not in tc:
                tc[path] = texture_rgba(path, clamp=False)
                self._textures.append(tc[path])
            return tc[path]
        self._sp: "list[dict[str, Any]]" = []
        for sd in self.species:
            with np.load(sd["npz"]) as d:
                ok = sd["o_keys"]
                bk = sd["b_keys"]
                op = [d[k] for k in ok]
                bp = [d[k] for k in bk]
            ibuf = InstanceBuffer()
            self._buffers.append(ibuf.id)
            ov, onc = self._mkvao(op[0], op[1], op[2], op[3], ibuf)
            bv, bnc = self._mkvao(bp[0], bp[1], bp[2], bp[3], ibuf)
            self._sp.append(dict(buf=ibuf, o=(ov, onc, tex(sd["o_tex"])), b=(bv, bnc, tex(sd["b_tex"]))))
        self.U = {x: glGetUniformLocation(self._prog, x) for x in
                  ("uModelView", "uProjection", "atlas", "sunDirEye", "sunColor",
                   "skyAmbient", "groundAmbient", "fogDensity", "fogColor",
                   "uLodStart", "uLodEnd", "uUpEye")}
        self._commit_constants()
        self._gl = self._prog

    def _upload_constants(self) -> None:
        U = self.U
        glUniform1i(U["atlas"], 0)
        glUniform3f(U["sunColor"], 1.25, 1.18, 1.02)
        glUniform3f(U["skyAmbient"], 0.5, 0.58, 0.66)
        glUniform3f(U["groundAmbient"], 0.14, 0.16, 0.11)
        glUniform1f(U["fogDensity"], 0.00016)
        glUniform3f(U["fogColor"], 0.46, 0.58, 0.76)
        glUniform1f(U["uLodStart"], LOD_NEAR)
        glUniform1f(U["uLodEnd"], LOD_FAR)

    def dispose(self) -> None:
        """Free this node's GL objects (VAOs, buffers, textures, program). GL thread."""
        if self._gl is None:
            return
        delete_gl(vaos=self._vaos, buffers=self._buffers,
                  textures=self._textures, programs=[self._prog])
        self._vaos = []
        self._buffers = []
        self._textures = []
        self._sp = []
        self._gl = None

    def _stream(self) -> bool:
        if self._pending is not None:
            for s, inst in self._pending.items():
                self._sp[s]["buf"].upload(inst)
            self._pending = None
        return any(s["buf"].count for s in self._sp)

    def _draw(self, mode: Any) -> None:
        # single alpha-cutout pass, depth-write on, no blend -> depth-correct, no bleed
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)
        for s in self._sp:
            n = s["buf"].count
            if not n:
                continue
            for part in ("o", "b"):
                v, cnt, t = s[part]
                glBindTexture(GL_TEXTURE_2D, t)
                glBindVertexArray(v)
                glDrawElementsInstanced(GL_TRIANGLES, cnt, GL_UNSIGNED_INT, None, n)
        glBindVertexArray(0)
