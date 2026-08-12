"""Shared base for the GPU-instanced vegetation nodes.

:class:`InstancedVegBase` factors out the render preamble the instanced veg nodes
repeat: the shadow/visible guard, lazy GL init, program save/restore (so the node
composes with whatever driving pass is bound), the per-frame matrix and eye-space
sun/up uploads, and the local draw-state wrapping. Subclasses supply only their
staged-instance upload, their constant uniforms, and their specific instanced draw.

:data:`LOD_NEAR`/:data:`LOD_FAR` are the single mesh-to-impostor cross-fade window.
The near mesh dithers OUT and the impostor billboard dithers IN across the SAME
window; sharing one constant pair keeps the two shaders complementary so the
handoff never shows a seam or a double-draw.
"""
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_CCW, GL_CURRENT_PROGRAM, GL_FALSE, glGetIntegerv, glUniform3f,
    glUniformMatrix4fv, glUseProgram,
)
from vrml.vrml97 import basenodes as vnodes
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import ensure_gl

#: node AABB kept large so a camera-following field is never frustum-culled whole.
_BIG = (1.0e6, 1.0e6, 1.0e6)

#: eye-distance window (world units) over which the near mesh hands off to the
#: impostor billboard. Both shaders read it, so the two sides cannot drift apart.
LOD_NEAR = 38.0
LOD_FAR = 52.0

_UP_WORLD = np.array([0.0, 1.0, 0.0])


class InstancedVegBase(vnodes.PointSet):
    """Base for the instanced vegetation nodes; drives the shared render preamble.

    A subclass sets ``self._prog`` (its program), ``self.U`` (uniform-name ->
    location), ``self.bounds``, and — for mesh nodes lit by an eye-space sun —
    ``self.sun`` (a normalized world-space direction). It implements
    :meth:`_upload_constants`, :meth:`_stream`, and :meth:`_draw`.
    """
    _BIG = _BIG
    #: world-space sun direction, or None for the camera-faced billboards, which use
    #: a flat sun term rather than a per-fragment eye-space sun vector.
    sun: "Optional[np.ndarray]" = None

    def boundingVolume(self, mode: Any) -> "boundingvolume.AABoundingBox":
        return boundingvolume.AABoundingBox(size=self.bounds, center=(0, 0, 0))

    def _commit_constants(self) -> None:
        """Send the never-per-frame uniforms once, at GL init, program saved/restored."""
        prev = int(glGetIntegerv(GL_CURRENT_PROGRAM))
        glUseProgram(self._prog)
        self._upload_constants()
        glUseProgram(prev)

    def _upload_constants(self) -> None:
        """Upload uniforms constant for this node's lifetime (program already bound)."""

    def _stream(self) -> bool:
        """Upload any staged per-instance data; return True if there is anything to draw."""
        raise NotImplementedError

    def _draw(self, mode: Any) -> None:
        """Bind VAO(s)/textures + per-frame uniforms and issue the instanced draw."""
        raise NotImplementedError

    def render(self, mode: Any = None, **kw: Any) -> int:
        if getattr(mode, 'shadow_pass', False) or not getattr(mode, 'visible', True):
            return 1
        if not ensure_gl(self):
            return 1
        if not self._stream():
            return 1
        # Import here (not at module load) to avoid a passes<->scenegraph import cycle;
        # this is the same deferral PBRMesh._apply_draw_state uses.
        from OpenGLContext.passes.instancing import set_cull_state
        U = self.U
        prev = mode.current_program() if hasattr(mode, "current_program") else 0
        glUseProgram(self._prog)
        glUniformMatrix4fv(U["uModelView"], 1, GL_FALSE, np.ascontiguousarray(mode.matrix, np.float32))
        glUniformMatrix4fv(U["uProjection"], 1, GL_FALSE, np.ascontiguousarray(mode.projection, np.float32))
        nm = np.asarray(mode.matrix)[:3, :3].T   # normal-matrix path shared by sun and up
        if self.sun is not None:
            se = nm @ self.sun
            se /= np.linalg.norm(se)
            glUniform3f(U["sunDirEye"], *se.astype(np.float32))
        if U.get("uUpEye", -1) != -1:
            ue = nm @ _UP_WORLD
            ue /= np.linalg.norm(ue)
            glUniform3f(U["uUpEye"], *ue.astype(np.float32))
        # Foliage draws double-sided. Cull goes through the pass's CPU state memo so
        # the pass re-issues its own winding on its next mesh, instead of this node
        # snapshotting live GL with glGet and restoring it. The pass restores the
        # program the node borrowed via current_program().
        set_cull_state(mode, False, GL_CCW)
        self._draw(mode)
        glUseProgram(prev)
        return 1
