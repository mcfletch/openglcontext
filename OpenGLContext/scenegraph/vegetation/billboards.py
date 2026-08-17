"""GPU-instanced camera-facing billboards for grass and tree impostors.

One draw call renders every instance: a single quad, turned to face the camera in
the vertex shader, scaled and yawed per instance. The fragment shader supports two
distance-fade modes so the same node serves both roles in an LOD scheme:

- ``near_fade`` — tree *impostor*: dithered cross-fade with a near mesh. Fully
  dithered out close up (the mesh is drawn instead), dithering in with distance.
- ``far_fade`` / ``near_cut`` — *grass*: a distance window. Tufts dissolve toward
  the follow-disc edge (``far_fade``) so they don't pop as the disc recentres on a
  walking camera, and an optional inner ``near_cut`` fades a coarse far layer in
  exactly where a fine near layer fades out.

Per-instance data (position, yaw, scale, and how much of the sun reaches it)
can be replaced each frame with :meth:`update_instances` for a
camera-following field.
"""
import ctypes
from typing import Any

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_DEPTH_TEST, GL_FALSE, GL_FLOAT, GL_STATIC_DRAW,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TRIANGLES, glActiveTexture, glBindBuffer,
    glBindTexture, glBindVertexArray, glBufferData, glDrawArraysInstanced,
    glEnable, glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays,
    glGetUniformLocation, glUniform1f, glUniform1i, glUniform3f, glVertexAttribPointer,
)
from OpenGLContext.scenegraph.instancedgl import (
    load_program, texture_rgba, delete_gl, setup_instance_attribs,
    instance_rows, InstanceBuffer)
from OpenGLContext.scenegraph.vegetation.base import (
    InstancedVegBase, _BIG, LOD_NEAR, LOD_FAR)


class InstancedBillboards(InstancedVegBase):
    """Instanced camera-facing billboards.

    :param positions: (N, 3) world positions of the instance bases.
    :param yaws: (N,) yaw radians per instance.
    :param scales: (N,) height scale per instance (world units).
    :param shades: optional (N,) sun reaching each instance, in [0, 1].
    :param texture: path to the RGBA billboard texture.
    :param width: quad width as a fraction of its height.
    :param near_fade: enable the impostor dithered near/far cross-fade.
    :param far_fade: >0 enables the grass outer dissolve at this eye distance.
    :param near_cut: >0 adds an inner fade-in ending at this eye distance.
    :param bounds: (sx, sy, sz) node bounding box (kept large so a follow-field is
        never frustum-culled as a whole).
    """
    def __init__(self, positions: np.ndarray, yaws: np.ndarray, scales: np.ndarray,
                 texture: str, width: float = 0.62, near_fade: bool = False,
                 far_fade: float = 0.0, near_cut: float = 0.0, sun_level: float = 0.5,
                 bounds: "tuple[float, float, float]" = _BIG) -> None:
        super(InstancedBillboards, self).__init__()
        self.pos = np.asarray(positions, np.float32)
        self.yaws = np.asarray(yaws, np.float32)
        self.scales = np.asarray(scales, np.float32)
        self.shades: "np.ndarray | None" = None
        self.texture = texture
        self.width = width
        self.near_fade = near_fade
        self.far_fade = float(far_fade)
        self.near_cut = float(near_cut)
        self.sun_level = float(sun_level)
        self.bounds = bounds
        self._gl: Any = None
        self._pending = False
        self._disabled = False

    def _instance_rows(self) -> np.ndarray:
        return instance_rows(self.pos, self.yaws, self.scales, self.shades)

    def _init_gl(self) -> None:
        self._prog = load_program("veg_billboard.vert", "veg_billboard.frag")
        # single quad, camera-faced in the vertex shader: x in [-0.5,0.5], y in [0,1].
        # v is flipped (1 at the base) because textures store row 0 at the top.
        mesh = np.array([(-0.5, 0, 0, 0, 1), (0.5, 0, 0, 1, 1), (0.5, 1, 0, 1, 0),
                         (-0.5, 0, 0, 0, 1), (0.5, 1, 0, 1, 0), (-0.5, 1, 0, 0, 0)], np.float32)
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)
        self._mvb = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._mvb)
        glBufferData(GL_ARRAY_BUFFER, mesh.nbytes, mesh, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        self._ibuf = InstanceBuffer()
        glBindBuffer(GL_ARRAY_BUFFER, self._ibuf.id)
        setup_instance_attribs(2, 3, 4)
        self._ibuf.upload(self._instance_rows())
        glBindVertexArray(0)
        self._tex = texture_rgba(self.texture, srgb=True)
        self.U = {n: glGetUniformLocation(self._prog, n) for n in
                  ("uModelView", "uProjection", "pine", "uWidth", "uNearFade", "uFarFade",
                   "uNearCut", "uSunLevel", "uLodStart", "uLodEnd", "sunColor",
                   "skyAmbient", "groundAmbient", "fogDensity", "fogColor")}
        self._commit_constants()
        self._gl = self._prog

    def _upload_constants(self) -> None:
        U = self.U
        glUniform1i(U["pine"], 0)
        glUniform1f(U["uWidth"], self.width)
        glUniform1f(U["uNearFade"], 1.0 if self.near_fade else 0.0)
        glUniform1f(U["uFarFade"], self.far_fade)
        glUniform1f(U["uNearCut"], self.near_cut)
        glUniform1f(U["uSunLevel"], self.sun_level)
        glUniform1f(U["uLodStart"], LOD_NEAR)
        glUniform1f(U["uLodEnd"], LOD_FAR)
        glUniform3f(U["sunColor"], 1.3, 1.22, 1.05)
        glUniform3f(U["skyAmbient"], 0.5, 0.58, 0.66)
        glUniform3f(U["groundAmbient"], 0.14, 0.16, 0.11)
        glUniform1f(U["fogDensity"], 0.00016)
        glUniform3f(U["fogColor"], 0.46, 0.58, 0.76)

    def dispose(self) -> None:
        """Free this node's GL objects (VAO, buffers, texture, program). GL thread."""
        if not self._gl:
            return
        delete_gl(vaos=[self._vao], buffers=[self._mvb, self._ibuf.id],
                  textures=[self._tex], programs=[self._prog])
        self._gl = None

    def update_instances(self, positions: np.ndarray, yaws: np.ndarray,
                         scales: np.ndarray,
                         shades: "np.ndarray | None" = None) -> None:
        """Stage new per-instance data; uploaded on the GL thread in :meth:`render`.

        ``shades`` is how much of the sun reaches each instance, in [0, 1]; left
        out, the whole set is in full sun.
        """
        self.pos = np.asarray(positions, np.float32)
        self.yaws = np.asarray(yaws, np.float32)
        self.scales = np.asarray(scales, np.float32)
        self.shades = None if shades is None else np.asarray(shades, np.float32)
        self._instance_rows()                    # report a mismatch to the caller
        self._pending = True

    def _stream(self) -> bool:
        if self._pending:
            self._ibuf.upload(self._instance_rows())
            self._pending = False
        return self._ibuf.count > 0

    def _draw(self, mode: Any) -> None:
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._tex)
        glEnable(GL_DEPTH_TEST)
        glBindVertexArray(self._vao)
        glDrawArraysInstanced(GL_TRIANGLES, 0, 6, self._ibuf.count)
        glBindVertexArray(0)
