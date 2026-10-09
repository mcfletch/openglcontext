"""Order-independent transparency: weighted blended, as X_ITE draws it

``ContextDefinition.orderIndependentTransparency``
(``OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY``, off by default, X_ITE's
default too) draws a view's transparent surfaces into two targets instead of
blending them over the frame in back-to-front order:

- the first adds each fragment's colour times its opacity ``a`` and a weight
  ``w``, and keeps the product of ``1 - a`` in its alpha;
- the second adds ``a * w``.

The composite then lays ``(1 - product) * sum(c a w) / sum(a w)`` over the
opaque scene. The weight (:func:`weight`) favours nearer and more opaque
fragments; with it, two surfaces of equal opacity at nearly equal depths
are mixed evenly, whichever is drawn first. The weight and the composite are
X_ITE 16.4.3's (``OIT2`` and ``OITCompose2``, MIT licence, see
license.txt), the method McGuire and Bavoil's.

The targets take the view's own depth copy as their depth buffer
(:meth:`OpenGLContext.passes.volumepass.VolumePassMixin.opaqueDepth`), so the
opaque scene hides what is behind it. The shaders' side is
``shaders/_oit_inc.glsl``; :class:`OITTargets` holds the GL side.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from OpenGL import GL
from OpenGL.GL import shaders as GL_shaders

log = logging.getLogger(__name__)

__all__ = ['enabled', 'weight', 'OITTargets']


def default_enabled() -> bool:
    """``OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY``, else off"""
    from OpenGLContext import renderoptions
    return renderoptions.env_flag_once('OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY', False)


def enabled(source: Any) -> bool:
    """Whether ``source``'s definition draws transparency order-independently"""
    from OpenGLContext import renderoptions
    return renderoptions.flag(source, 'orderIndependentTransparency', default_enabled())


def weight(alpha: float, depth: float) -> float:
    """The weight of a fragment of opacity ``alpha`` at window depth ``depth`` (0 to 1)"""
    found = (min(1.0, alpha * 10.0) + 0.01) ** 3 * 1e8 * (1.0 - depth * 0.9) ** 3
    return float(min(max(found, 1e-2), 3e3))


_VERTEX = """#version 330 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""

#: The composite, over the target the frame was being drawn into, blended by
#: (ONE, ONE_MINUS_SRC_ALPHA).
_COMPOSE = """#version 330 core
uniform sampler2D accumulated;   // sum(c a w), product(1 - a)
uniform sampler2D weights;       // sum(a w)
uniform vec2 origin;             // the view's lower left corner in the window
out vec4 fragColor;
void main() {
    ivec2 at = ivec2(gl_FragCoord.xy - origin);
    vec4 accum = texelFetch(accumulated, at, 0);
    if (accum.a >= 1.0) discard;
    float total = texelFetch(weights, at, 0).r;
    float covered = 1.0 - accum.a;
    fragColor = vec4(covered * accum.rgb / clamp(total, 0.001, 50000.0), covered);
}"""


def _texture(width: int, height: int) -> int:
    texture = int(GL.glGenTextures(1))
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA16F, width, height, 0, GL.GL_RGBA,
                    GL.GL_FLOAT, None)
    for parameter, value in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST),
                             (GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST),
                             (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
                             (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
        GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return texture


class OITTargets:
    """The two targets one view's transparent surfaces are drawn into, and the composite

    Made at the view's size and remade when it changes; :meth:`release`
    deletes them in the context that made them.
    """

    def __init__(self) -> None:
        self.size: Optional[tuple[int, int]] = None
        self.framebuffer = 0
        self.textures: tuple[int, int] = (0, 0)
        self.program = 0
        self.vertex_array = 0
        self._previous = 0
        self._viewport: tuple[int, int, int, int] = (0, 0, 0, 0)

    def _ensure(self, width: int, height: int) -> None:
        if self.size != (width, height):
            self._release_targets()
            self.textures = (_texture(width, height), _texture(width, height))
            self.framebuffer = int(GL.glGenFramebuffers(1))
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
            for attachment, texture in zip((GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1),
                                           self.textures):
                GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, attachment, GL.GL_TEXTURE_2D,
                                          texture, 0)
            GL.glDrawBuffers(2, np.array([GL.GL_COLOR_ATTACHMENT0, GL.GL_COLOR_ATTACHMENT1],
                                         np.uint32))
            self.size = (width, height)
        if not self.program:
            self.program = int(GL_shaders.compileProgram(
                GL_shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER),
                GL_shaders.compileShader(_COMPOSE, GL.GL_FRAGMENT_SHADER), validate=False))
            self.vertex_array = int(GL.glGenVertexArrays(1))

    def begin(self, viewport: tuple[int, int, int, int], depth: int) -> bool:
        """Draw what follows into the targets, depth-tested against the texture ``depth``

        ``viewport`` is the view's rectangle in the window; the targets are its
        size. Answers whether the targets are ready; where not, nothing is
        changed and the caller blends in order.
        """
        x, y, width, height = (int(value) for value in viewport)
        self._previous = int(GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING))
        self._ensure(max(1, width), max(1, height))
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT, GL.GL_TEXTURE_2D,
                                  depth, 0)
        if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._previous)
            return False
        self._viewport = (x, y, width, height)
        GL.glViewport(0, 0, width, height)
        scissored = GL.glIsEnabled(GL.GL_SCISSOR_TEST)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if scissored:
            GL.glEnable(GL.GL_SCISSOR_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFuncSeparate(GL.GL_ONE, GL.GL_ONE, GL.GL_ZERO, GL.GL_ONE_MINUS_SRC_ALPHA)
        return True

    def compose(self) -> None:
        """Lay the targets over the view in the framebuffer :meth:`begin` found bound"""
        x, y, width, height = self._viewport
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._previous)
        GL.glViewport(x, y, width, height)
        GL.glUseProgram(self.program)
        for unit, (name, texture) in enumerate(zip(('accumulated', 'weights'), self.textures)):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, name), unit)
        GL.glUniform2f(GL.glGetUniformLocation(self.program, 'origin'), float(x), float(y))
        depth_test = GL.glIsEnabled(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glBindVertexArray(self.vertex_array)
        try:
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        finally:
            GL.glBindVertexArray(0)
            for unit in (1, 0):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUseProgram(0)
            if depth_test:
                GL.glEnable(GL.GL_DEPTH_TEST)

    def _release_targets(self) -> None:
        if self.framebuffer:
            GL.glDeleteFramebuffers(1, np.array([self.framebuffer], np.uint32))
        if any(self.textures):
            GL.glDeleteTextures(2, np.array(self.textures, np.uint32))
        self.framebuffer, self.textures, self.size = 0, (0, 0), None

    def release(self) -> None:
        """Delete the targets, the composite program and its vertex array"""
        self._release_targets()
        if self.program:
            GL.glDeleteProgram(self.program)
            GL.glDeleteVertexArrays(1, np.array([self.vertex_array], np.uint32))
        self.program = self.vertex_array = 0
