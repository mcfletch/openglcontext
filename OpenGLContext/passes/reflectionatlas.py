"""The one texture every reflection of a frame is drawn into, and read from.

Each reflection is a tile of :class:`ReflectionAtlas`, placed by
:class:`~OpenGLContext.passes.reflectiontiles.TilePacker`. One target means one
framebuffer takes every viewport of a shared submission, and one texture bound
on :data:`~OpenGLContext.passes.reflection.REFLECTION_UNIT` serves every
reflective draw of the frame, so no reflective draw rebinds a texture. Its size
is a share of the window's pixels (``ContextDefinition.reflectionAtlas``,
:func:`atlas_size`), however many mirrors there are.

The colour is linear HDR (``RGBA16F``) with alpha 0 wherever a mirror view
drew nothing, which is where a mirror shows the environment probe. Three mip
levels are allocated for rough mirrors, which read a blurred level; the
four-texel gutter round each tile keeps those levels inside it.

A mirror seen in another mirror shows the reflection it had the frame before.
:meth:`ReflectionAtlas.keep` copies the atlas aside before a frame's mirror
views are drawn, and they read the copy, since a draw may not read the texture
it is drawing into.
"""
from __future__ import annotations

import math
from typing import Tuple

from OpenGLContext.passes.reflection import REFLECTION_UNIT

__all__ = ['LEVELS', 'FILL', 'atlas_size', 'ReflectionAtlas']

#: Mip levels the atlas holds: the full texels and two blurred ones.
LEVELS = 3

#: The share of the atlas a frame's tiles are budgeted to fill. Shelves of
#: power-of-two heights and a gutter round every tile leave the rest empty, so
#: a budget of the whole atlas would ask for tiles the packer cannot place.
FILL = 0.5

#: Atlas sides are a multiple of this many texels.
_STEP = 16


def atlas_size(width: int, height: int, share: float) -> Tuple[int, int]:
    """An atlas of ``share`` of a ``width`` by ``height`` window's pixels.

    The window's own shape, each side scaled by the square root of the share
    and rounded up to a multiple of 16 texels.
    """
    side = math.sqrt(max(float(share), 0.0))

    def texels(extent: float) -> int:
        return max(_STEP, int(math.ceil(extent * side / _STEP)) * _STEP)

    return texels(width), texels(height)


class ReflectionAtlas:
    """Linear HDR colour and depth, with a tile per reflection.

    Allocated on first use and again whenever the size it is asked for
    changes, which clears every tile.
    """

    UNIT = REFLECTION_UNIT

    def __init__(self) -> None:
        self.size: Tuple[int, int] = (0, 0)
        self.framebuffer = 0
        self.texture = 0
        self.depth = 0
        #: Whether the blurred levels hold what level 0 holds.
        self.mipmapped = False
        #: The copy of the last frame's reflections, and its framebuffer.
        self.kept = 0
        self._kept_framebuffer = 0

    def ensure_size(self, width: int, height: int) -> bool:
        """Hold an atlas of ``width`` by ``height`` texels; True where it was made anew."""
        from OpenGL import GL as gl
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == self.size and self.framebuffer:
            return False
        self.release()
        self.texture = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexStorage2D(gl.GL_TEXTURE_2D, LEVELS, gl.GL_RGBA16F, width, height)
        for name, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR),
                            (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                            (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                            (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE),
                            (gl.GL_TEXTURE_MAX_LEVEL, LEVELS - 1)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, name, value)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self.depth = int(gl.glGenRenderbuffers(1))
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self.depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24,
                                 width, height)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, 0)
        previous = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        self.framebuffer = int(gl.glGenFramebuffers(1))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, self.texture, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self.depth)
        gl.glDrawBuffers(1, [gl.GL_COLOR_ATTACHMENT0])
        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)
        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            self.release()
            raise RuntimeError('the reflection atlas is incomplete (0x%x)' % int(status))
        self.size = (width, height)
        return True

    def keep(self) -> None:
        """Copy the atlas aside, for the mirror views about to be drawn to read."""
        from OpenGL import GL as gl
        width, height = self.size
        previous = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        if not self.kept:
            self.kept = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.kept)
            gl.glTexStorage2D(gl.GL_TEXTURE_2D, 1, gl.GL_RGBA16F, width, height)
            for name, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                                (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                                (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                                (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, name, value)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            self._kept_framebuffer = int(gl.glGenFramebuffers(1))
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._kept_framebuffer)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, self.kept, 0)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.framebuffer)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self._kept_framebuffer)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glBlitFramebuffer(0, 0, width, height, 0, 0, width, height,
                             gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)

    def bind_kept(self) -> None:
        """Put the copy :meth:`keep` made on :data:`REFLECTION_UNIT`."""
        from OpenGL import GL as gl
        gl.glActiveTexture(gl.GL_TEXTURE0 + self.UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.kept)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def begin(self) -> int:
        """Draw into the atlas from here; answers the framebuffer to go back to."""
        from OpenGL import GL as gl
        previous = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        self.mipmapped = False
        return previous

    def clear(self, rect: Tuple[int, int, int, int]) -> None:
        """Clear one tile to nothing: alpha 0, the far plane."""
        from OpenGL import GL as gl
        gl.glViewport(*rect)
        gl.glScissor(*rect)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def end(self, previous: int, mipmap: bool = False) -> None:
        """Stop drawing into the atlas, blurring its levels where ``mipmap``."""
        from OpenGL import GL as gl
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)
        if mipmap:
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            self.mipmapped = True

    def bind(self) -> None:
        """Put the atlas on :data:`REFLECTION_UNIT` for the mirrors to read."""
        from OpenGL import GL as gl
        gl.glActiveTexture(gl.GL_TEXTURE0 + self.UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def release(self) -> None:
        """Give back the atlas's GL names; the next use allocates again."""
        from OpenGL import GL as gl
        if self.framebuffer:
            gl.glDeleteFramebuffers(1, [self.framebuffer])
        if self.texture:
            gl.glDeleteTextures([self.texture])
        if self.depth:
            gl.glDeleteRenderbuffers(1, [self.depth])
        if self._kept_framebuffer:
            gl.glDeleteFramebuffers(1, [self._kept_framebuffer])
        if self.kept:
            gl.glDeleteTextures([self.kept])
        self.framebuffer = self.texture = self.depth = 0
        self.kept = self._kept_framebuffer = 0
        self.size = (0, 0)
        self.mipmapped = False
