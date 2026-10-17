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
from vrml import field
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_DEPTH_TEST, GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE, GL_FLOAT, GL_STATIC_DRAW, GL_TEXTURE0, GL_TEXTURE_2D, GL_TRIANGLES,
    GL_TRUE, GL_UNSIGNED_INT, glActiveTexture, glBindBuffer, glBindTexture,
    glBindVertexArray, glBufferData, glDepthMask, glDisable, glDrawElementsInstanced,
    glEnable, glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays,
    glGetUniformLocation, glUniform1f, glUniform1i, glUniform3f,
    glUniformMatrix4fv, glUseProgram, glVertexAttribPointer,
)
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import (
    FOG_UNIFORMS, load_program, texture_rgba, delete_gl, setup_instance_attribs,
    instance_rows, InstanceBuffer)
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

    The trees drawn are the trees near the camera, and that is all the node is bounded
    by, so in a Shape that casts shadows they are written into the sun's shadow maps
    without the maps being stretched over the whole forest. Trees beyond them are the
    impostors', which cast none.
    """
    #: How many near sets have been staged: what the node's bound is cached against.
    generation = field.newField('generation', 'SFInt32', 0, 0)

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
        #: Optional (N,) sun reaching each instance, in [0, 1].
        self.all_shade: "Optional[np.ndarray]" = None
        self.species = species
        self.sun = np.asarray(sun, 'd')
        self.sun /= np.linalg.norm(self.sun)
        self.bounds = bounds
        self._gl: Any = None
        self._pending: "Optional[dict[int, np.ndarray]]" = None
        #: The corners of the box the near set stands in, once one has been staged.
        self._box: "Optional[tuple[np.ndarray, np.ndarray]]" = None

    def compute_pending(self, cx: float, cz: float,
                        radius: float = 42.0) -> "dict[int, np.ndarray]":
        """Per-species ``(x,y,z,yaw,scale)`` arrays for trees within ``radius`` of ``(cx, cz)``.

        Reads only the immutable ``all_*`` tables and returns fresh arrays, touching
        no GL and no node state, so a background streaming thread can build the next
        near-set off the render thread. The caller hands the result to
        :meth:`stage` on the GL thread, and the next draw uploads it."""
        d2 = (self.all_pos[:, 0] - cx) ** 2 + (self.all_pos[:, 2] - cz) ** 2
        near = d2 < radius * radius
        return {
            s: instance_rows(self.all_pos[near & (self.all_sp == s)],
                             self.all_yaw[near & (self.all_sp == s)],
                             self.all_scale[near & (self.all_sp == s)],
                             None if self.all_shade is None
                             else self.all_shade[near & (self.all_sp == s)])
            for s in range(len(self.species))}

    def update(self, cx: float, cz: float, radius: float = 42.0) -> None:
        """Select trees within ``radius`` of ``(cx, cz)`` and stage their instance data."""
        self.stage(self.compute_pending(cx, cz, radius))

    def stage(self, pending: "dict[int, np.ndarray]") -> None:
        """Draw ``pending``, a :meth:`compute_pending` result, from the next draw on.

        Called on the GL thread; the upload happens in that draw. A set staged
        before an earlier one was drawn replaces it.
        """
        self._pending = pending
        self._box = _box_of(pending.values())
        self.generation += 1

    def boundingVolume(self, mode: Any) -> Any:
        """The box the trees drawn stand in, crowns included; all of space before a near
        set has been staged, and nothing where it holds no tree.

        The same object while the trees drawn are the same ones and a new one when they change.
        The shadow pass keeps a caster's depth maps and world geometry for as long as its bound
        is the same object, and it is cached against :attr:`generation`, which :meth:`stage`
        counts up, so what caches it here and in the shape holding it lets go.
        """
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current
        if self._box is None:
            volume = super().boundingVolume(mode)
        else:
            low, high = self._box
            volume = boundingvolume.AABoundingBox(
                size=tuple(float(v) for v in high - low),
                center=tuple(float(v) for v in (low + high) / 2.0))
        return boundingvolume.cacheVolume(self, volume, ((self, "generation"),))

    @property
    def staged(self) -> "Optional[dict[int, np.ndarray]]":
        """The near set waiting for the next draw to upload it, or None."""
        return self._pending

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
        setup_instance_attribs(3, 4, 5)
        glBindVertexArray(0)
        self._vaos.append(vao)
        self._buffers += [mvb, ib]
        return vao, len(idx)

    def _init_gl(self) -> None:
        self._prog = load_program("veg_mesh.vert", "veg_mesh.frag")
        #: The program a shadow map is drawn with: the same vertices, and only the cutout.
        self._depth_prog = load_program("veg_mesh.vert", "veg_depth.frag")
        self._depth_U = {name: glGetUniformLocation(self._depth_prog, name)
                         for name in ("uModelView", "uProjection", "atlas")}
        # Retain every generated handle so dispose() can free it -- the mesh/index
        # VBOs would otherwise be unreachable the moment _mkvao returns.
        self._vaos: "list[Any]" = []
        self._buffers: "list[Any]" = []
        self._textures: "list[Any]" = []
        tc: "dict[str, Any]" = {}

        def tex(path: str) -> Any:
            if path not in tc:
                tc[path] = texture_rgba(path, clamp=False, srgb=True)
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
                   "skyAmbient", "groundAmbient", *FOG_UNIFORMS,
                   "uLodStart", "uLodEnd", "uUpEye")}
        self._commit_constants("veg_mesh.vert", "veg_mesh.frag")
        self._gl = self._prog

    def _upload_constants(self, U: "dict[str, int]") -> None:
        glUniform1i(U["atlas"], 0)
        glUniform3f(U["sunColor"], 1.25, 1.18, 1.02)
        glUniform3f(U["skyAmbient"], 0.5, 0.58, 0.66)
        glUniform3f(U["groundAmbient"], 0.14, 0.16, 0.11)
        glUniform1f(U["uLodStart"], LOD_NEAR)
        glUniform1f(U["uLodEnd"], LOD_FAR)

    def dispose(self) -> None:
        """Free this node's GL objects (VAOs, buffers, textures, program). GL thread."""
        if self._gl is None:
            return
        delete_gl(vaos=self._vaos, buffers=self._buffers, textures=self._textures,
                  programs=[*self.programs.programs(), self._depth_prog])
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

    def render(self, mode: Any = None, **kw: Any) -> int:
        """Draw the trees, or write them into the shadow map being made."""
        if getattr(mode, 'shadow_pass', False):
            return self._render_depth(mode)
        return super().render(mode, **kw)

    def _render_depth(self, mode: Any) -> int:
        """Write the near trees' depth for a shadow map.

        The pass has set the light's view and projection as ``mode.matrix`` and
        ``mode.projection`` and bound its own program; this draws through its own, and
        puts the pass's back.
        """
        if not self.ensure_gl() or not self._stream():
            return 1
        previous = mode.current_program() if hasattr(mode, "current_program") else 0
        glUseProgram(self._depth_prog)
        glUniformMatrix4fv(self._depth_U["uModelView"], 1, GL_FALSE,
                           np.ascontiguousarray(mode.matrix, np.float32))
        glUniformMatrix4fv(self._depth_U["uProjection"], 1, GL_FALSE,
                           np.ascontiguousarray(mode.projection, np.float32))
        glUniform1i(self._depth_U["atlas"], 0)
        self._draw(mode)
        glUseProgram(previous)
        return 1

    def _draw(self, mode: Any) -> None:
        # single alpha-cutout pass, depth-write on, no blend -> depth-correct, no bleed
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)
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
                with self._instanced(mode) as copies:
                    glDrawElementsInstanced(GL_TRIANGLES, cnt, GL_UNSIGNED_INT, None,
                                            n * copies)
        glBindVertexArray(0)


#: How much of a tree's height its crown reaches out to either side of the trunk, and how far
#: above its base the tip of it stands.
CROWN_SPREAD = 0.6
CROWN_RISE = 1.1


def _box_of(sets: Any) -> "tuple[np.ndarray, np.ndarray]":
    """The box the trees of ``sets``, each an (N, k) array of ``x, y, z, yaw, height``
    rows, stand in with their crowns; a point where there are none."""
    rows = [rows for rows in sets if len(rows)]
    if not rows:
        return np.zeros(3), np.zeros(3)
    rows_all = np.concatenate(rows)
    low = rows_all[:, :3].min(axis=0).astype('d')
    high = rows_all[:, :3].max(axis=0).astype('d')
    tallest = float(rows_all[:, 4].max())
    low[[0, 2]] -= CROWN_SPREAD * tallest
    high[[0, 2]] += CROWN_SPREAD * tallest
    high[1] += CROWN_RISE * tallest
    return low, high
