"""Runtime multi-layer *splat* terrain node.

Renders a :class:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField` as a
single triangulated mesh, texturing it in the fragment shader from N detail
material layers (albedo/normal/roughness sampler arrays) blended per-pixel by an
RGBA control map. Detail + macro tiling hides repetition; a baked sun-shadow +
tree-canopy term is sampled for static shading. This is the crisp,
close-up-capable ground under the instanced vegetation.

The node drives raw core-profile GL in :meth:`render` (its own program, VAO and
textures). It composes with whatever render pass is driving the scenegraph by
restoring the pass's program (``mode.current_program()``) after its own draw and
routing its face-cull through the pass's CPU state memo (``set_cull_state``), so it
needs no ``glGet`` round-trip to snapshot live GL state.
"""
import ctypes
from typing import TYPE_CHECKING, Any, Callable, Optional

import numpy as np
from PIL import Image
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BACK, GL_CCW, GL_CLAMP_TO_EDGE, GL_DEPTH_TEST, GL_ELEMENT_ARRAY_BUFFER, GL_FALSE, GL_FLOAT, GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR, GL_R8, GL_RED, GL_REPEAT, GL_RGBA, GL_RGBA8, GL_STATIC_DRAW,
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_TEXTURE3, GL_TEXTURE4, GL_TEXTURE_2D,
    GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_UNSIGNED_BYTE, GL_UNSIGNED_INT, glActiveTexture,
    glBindBuffer, glBindTexture, glBindVertexArray, glBufferData, glCullFace,
    glDrawElements, glEnable, glEnableVertexAttribArray, glGenBuffers,
    glGenTextures, glGenVertexArrays, glGenerateMipmap, glGetUniformLocation, glTexImage2D, glTexImage3D, glTexParameteri, glTexSubImage3D,
    glUniform1f, glUniform1i, glUniform2f, glUniform3f, glUniformMatrix3fv,
    glUniformMatrix4fv, glUseProgram, glVertexAttribPointer,
)
from vrml.vrml97 import basenodes as vnodes
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import (
    load_program, texture_rgba, ensure_gl, delete_gl)

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

DEFAULT_SUN = (-0.5, -0.72, -0.48)

#: How dark it is under a canopy. ``CANOPY_SHADE`` is how hard a closed canopy
#: darkens the light and ``CANOPY_DEEPEST`` the most of it that may go, so what
#: is left where the canopy opens is the sun breaking through. A forest floor is
#: dark; the ground beside it is not, and the difference between them is most of
#: what makes a wood read as a wood rather than as trees on a lawn.
#:
#: ``CANOPY_CROWN`` is how wide a tree's crown is, in metres, which is the ground
#: one tree shades: a stand is closed when its crowns meet, not when its trunks
#: do. ``CANOPY_SPREAD`` offsets the shadow towards the sun, because a tree casts
#: along the light rather than straight down.
CANOPY_SHADE = 1.3
CANOPY_DEEPEST = 0.78
CANOPY_CROWN = 7.0
CANOPY_SPREAD = 12.0

# Detail-material tiling: DETAIL_SCALE repeats per world unit (crisp close-up),
# MACRO_SCALE a second, larger tiling mixed in to break the visible repeat.
DETAIL_SCALE = 0.35
MACRO_SCALE = 0.043
NORMAL_STRENGTH = 1.1
# Atmosphere. Kept in step with the vegetation nodes' lighting so the ground and
# the plants on it read under one sun: a warm key light, a hemispheric sky/ground
# ambient split, and exponential height fog.
SUN_COLOR = (1.3, 1.22, 1.05)
SKY_COLOR = (0.42, 0.52, 0.66)
GROUND_AMBIENT = (0.18, 0.17, 0.15)
FOG_DENSITY = 0.00016
FOG_COLOR = (0.46, 0.58, 0.76)


def _array_texture(kind: str, layers: "list[str]",
                   material_fn: "Callable[..., dict[str, Any]]",
                   size: int = 1024) -> int:
    """A GL_TEXTURE_2D_ARRAY of ``kind`` (color/normal/roughness) for each layer.

    ``material_fn(name, res)`` returns a dict with at least a ``color`` path and
    optionally ``normal``/``roughness`` paths (the ambientCG/cc0 material API)."""
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D_ARRAY, tid)
    glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, size, size, len(layers),
                 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
    for i, name in enumerate(layers):
        m = material_fn(name, "1K")
        p = m.get(kind) or m["color"]
        im = Image.open(p).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, i, size, size, 1,
                        GL_RGBA, GL_UNSIGNED_BYTE, np.asarray(im))
    glGenerateMipmap(GL_TEXTURE_2D_ARRAY)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_REPEAT)
    return tid


class SplatTerrain(vnodes.PointSet):
    """Splat-textured terrain over a :class:`HeightField`.

    Subclasses ``PointSet`` only to inherit the scenegraph render hook; it draws a
    triangulated indexed mesh through its own program/VAO, not points.

    :param height_field: the :class:`HeightField` to render and shade.
    :param layers: up to four material names, blended by the control map's RGBA.
    :param control: the RGBA splat control map -- a path, an open image, or the
        bytes of one.
    :param material_fn: ``material_fn(name, res)`` resolving a layer's texture paths;
        defaults to the cc0/ambientCG material fetcher.
    :param canopy: optional (N, 3) trunk positions; when set the baked shadow is
        darkened under tree cover for dappled shade. Set before first render.
    :param canopy_shade: how hard the canopy darkens what is under it, and
        :param canopy_deepest: the most it may, as a fraction of the light. A
        forest floor is *dark*; the light default reads as an orchard. What is
        left where the density is low is the sun breaking through.
    :param canopy_crown: how wide a tree's crown is in metres, which is the
        ground one tree shades.
    :param canopy_spread: how far the canopy's shadow is offset towards the sun,
        in metres -- trees cast along the light, not straight down.
    """
    def __init__(self, height_field: "HeightField", layers: "list[str]", control: Any,
                 sun: "tuple[float, float, float]" = DEFAULT_SUN,
                 material_fn: "Optional[Callable[..., dict[str, Any]]]" = None,
                 canopy: Optional[np.ndarray] = None,
                 canopy_shade: float = CANOPY_SHADE,
                 canopy_deepest: float = CANOPY_DEEPEST,
                 canopy_crown: float = CANOPY_CROWN,
                 canopy_spread: float = CANOPY_SPREAD) -> None:
        super(SplatTerrain, self).__init__()
        self.hf = height_field
        self.layers = layers
        self.control = control
        if material_fn is None:
            from OpenGLContext.loaders import cc0
            material_fn = cc0.material
        self.material_fn = material_fn
        self.sun = np.asarray(sun, 'd')
        self.sun /= np.linalg.norm(self.sun)
        self.canopy = canopy
        self.canopy_shade = float(canopy_shade)
        self.canopy_deepest = float(canopy_deepest)
        self.canopy_crown = float(canopy_crown)
        self.canopy_spread = float(canopy_spread)
        self._gl: Any = None
        self._shading: Any = None
        self._disabled = False

    @property
    def shading(self) -> np.ndarray:
        """How much of the sun reaches each cell of the ground, in [0, 1].

        The hillside's own shadow with the canopy's over it, on the height
        field's grid. It is what the terrain is drawn with, and it is public
        because everything else standing on this ground has to agree with it:
        grass lit like an open field under a closed canopy is a lamp on the
        forest floor. See :meth:`shade`.
        """
        if self._shading is None:
            lit = self.hf.sun_shadow(self.sun)
            if self.canopy is not None and len(self.canopy):
                lit = self.hf.canopy_shadow(lit, self.canopy, self.sun,
                                            spread=self.canopy_spread,
                                            crown=self.canopy_crown,
                                            darken=self.canopy_shade,
                                            cap=self.canopy_deepest)
            self._shading = lit
        return self._shading

    def shade(self, x: Any, z: Any) -> Any:
        """How much of the sun reaches these world positions, in [0, 1].

        Arrays in, array out, for a caller placing a great many things at once.
        """
        lit = self.shading
        size = lit.shape[0]
        extent = self.hf.extent
        u = np.clip((np.asarray(x, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        v = np.clip((np.asarray(z, 'd') + extent / 2.0) / extent * (size - 1),
                    0, size - 1).astype(int)
        return lit[v, u]

    def _init_gl(self) -> None:
        prog = load_program("terrain_splat.vert", "terrain_splat.frag")
        inter, idx = self.hf.mesh()
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)
        vb = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vb)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)
        ib = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        tex = dict(col=_array_texture("color", self.layers, self.material_fn),
                   nrm=_array_texture("normal", self.layers, self.material_fn),
                   rgh=_array_texture("roughness", self.layers, self.material_fn),
                   ctl=texture_rgba(self.control, clamp=True, mipmap=False))
        lit = self.shading
        st = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, st)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, lit.shape[1], lit.shape[0], 0,
                     GL_RED, GL_FLOAT, np.ascontiguousarray(lit))
        for pp, vv in [(GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                       (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)]:
            glTexParameteri(GL_TEXTURE_2D, pp, vv)
        tex["sun"] = st
        U = {n: glGetUniformLocation(prog, n) for n in
             ("layerColor", "layerNormal", "layerRough", "controlMap", "sunShadow",
              "numLayers", "worldMin", "worldSize", "detailScale", "macroScale",
              "normalStrength", "uModelView", "uProjection", "uNormalMatrix",
              "sunDirEye", "sunColor", "skyColor", "groundAmbient", "fogDensity", "fogColor")}
        self._gl = dict(prog=prog, vao=vao, vb=vb, ib=ib, ncount=len(idx), tex=tex, U=U)

    def dispose(self) -> None:
        """Free this node's GL objects (VAO, buffers, textures, program). GL thread."""
        g = self._gl
        if not g:
            return
        delete_gl(vaos=[g["vao"]], buffers=[g["vb"], g["ib"]],
                  textures=list(g["tex"].values()), programs=[g["prog"]])
        self._gl = None

    def boundingVolume(self, mode: Any) -> "boundingvolume.AABoundingBox":
        E = self.hf.extent
        H = self.hf.relief * 3
        return boundingvolume.AABoundingBox(
            size=(E, H, E), center=(0, self.hf.base + self.hf.relief / 2.0, 0))

    def render(self, mode: Any = None, **kw: Any) -> int:
        if getattr(mode, 'shadow_pass', False) or not getattr(mode, 'visible', True):
            return 1
        if not ensure_gl(self):
            return 1
        g = self._gl
        U = g["U"]
        E = self.hf.extent
        from OpenGLContext.passes.instancing import set_cull_state
        prev_prog = mode.current_program() if hasattr(mode, "current_program") else 0
        glUseProgram(g["prog"])
        glUniformMatrix4fv(U["uModelView"], 1, GL_FALSE, np.ascontiguousarray(mode.matrix, np.float32))
        glUniformMatrix4fv(U["uProjection"], 1, GL_FALSE, np.ascontiguousarray(mode.projection, np.float32))
        # The normal matrix is the plain modelview upper-3x3, correct while that
        # block is orthonormal (rotation only). The terrain carries no scale, so no
        # inverse-transpose is needed; a scaled terrain transform would skew normals.
        glUniformMatrix3fv(U["uNormalMatrix"], 1, GL_FALSE, np.ascontiguousarray(np.asarray(mode.matrix)[:3, :3], np.float32))
        se = np.asarray(mode.matrix)[:3, :3].T @ self.sun
        se /= np.linalg.norm(se)
        glUniform3f(U["sunDirEye"], *se.astype(np.float32))
        glUniform1i(U["layerColor"], 0)
        glUniform1i(U["layerNormal"], 1)
        glUniform1i(U["layerRough"], 2)
        glUniform1i(U["controlMap"], 3)
        glUniform1i(U["sunShadow"], 4)
        glUniform1i(U["numLayers"], len(self.layers))
        glUniform2f(U["worldMin"], -E / 2, -E / 2)
        glUniform2f(U["worldSize"], E, E)
        glUniform1f(U["detailScale"], DETAIL_SCALE)
        glUniform1f(U["macroScale"], MACRO_SCALE)
        glUniform1f(U["normalStrength"], NORMAL_STRENGTH)
        glUniform3f(U["sunColor"], *SUN_COLOR)
        glUniform3f(U["skyColor"], *SKY_COLOR)
        glUniform3f(U["groundAmbient"], *GROUND_AMBIENT)
        glUniform1f(U["fogDensity"], FOG_DENSITY)
        glUniform3f(U["fogColor"], *FOG_COLOR)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D_ARRAY, g["tex"]["col"])
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D_ARRAY, g["tex"]["nrm"])
        glActiveTexture(GL_TEXTURE2)
        glBindTexture(GL_TEXTURE_2D_ARRAY, g["tex"]["rgh"])
        glActiveTexture(GL_TEXTURE3)
        glBindTexture(GL_TEXTURE_2D, g["tex"]["ctl"])
        glActiveTexture(GL_TEXTURE4)
        glBindTexture(GL_TEXTURE_2D, g["tex"]["sun"])
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)
        # Back-face cull the ground; through the pass's cull memo so the next mesh
        # re-issues its own winding, with no glGet snapshot/restore of live state.
        set_cull_state(mode, True, GL_CCW)
        glCullFace(GL_BACK)
        glBindVertexArray(g["vao"])
        glDrawElements(GL_TRIANGLES, g["ncount"], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glUseProgram(prev_prog)
        return 1
