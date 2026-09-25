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
four-texel gutter round each tile keeps those levels inside it, and is cleared
with the tile, so what they blur in at the edge is nothing rather than
whatever a tile there held before.

A mirror seen in another mirror shows the reflection it had the frame before.
:meth:`ReflectionAtlas.keep` copies the tiles those reflections are in aside
before a frame's mirror views are drawn, and they read the copy, since a draw
may not read the texture it is drawing into.

Each call leaves the GL state it found: the clear colour, the texture on the
active unit and both framebuffer bindings. The atlas's texture is worked on
through :data:`~OpenGLContext.passes.reflection.REFLECTION_UNIT`, the unit it
is read from.
"""
from __future__ import annotations

import contextlib
import math
from collections.abc import Iterable, Iterator

from OpenGLContext.passes.reflection import REFLECTION_UNIT, TileRect
from OpenGLContext.passes.reflectiontiles import GUTTER

__all__ = ['LEVELS', 'FILL', 'atlas_size', 'ReflectionAtlas']

#: The draw and read framebuffers bound when the atlas was asked to draw.
Bindings = tuple[int, int]

#: Mip levels the atlas holds: the full texels and two blurred ones.
LEVELS = 3

#: The share of the atlas a frame's tiles are budgeted to fill. Shelves of
#: power-of-two heights and a gutter round every tile leave the rest empty, so
#: a budget of the whole atlas would ask for tiles the packer cannot place.
FILL = 0.5

#: Atlas sides are a multiple of this many texels.
_STEP = 16


def atlas_size(width: int, height: int, share: float) -> tuple[int, int]:
    """An atlas of ``share`` of a ``width`` by ``height`` window's pixels.

    The window's own shape, each side scaled by the square root of the share
    and rounded up to a multiple of 16 texels.
    """
    side = math.sqrt(max(float(share), 0.0))

    def texels(extent: float) -> int:
        return max(_STEP, int(math.ceil(extent * side / _STEP)) * _STEP)

    return texels(width), texels(height)


def _bindings() -> Bindings:
    from OpenGL import GL as gl
    return (int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)),
            int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)))


def _restore(bindings: Bindings) -> None:
    from OpenGL import GL as gl
    gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, bindings[0])
    gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, bindings[1])


class ReflectionAtlas:
    """Linear HDR colour and depth, with a tile per reflection.

    Allocated on first use and again whenever the size it is asked for
    changes, which clears every tile.
    """

    UNIT = REFLECTION_UNIT

    def __init__(self) -> None:
        self.size: tuple[int, int] = (0, 0)
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
        with self._on_unit(self.texture):
            gl.glTexStorage2D(gl.GL_TEXTURE_2D, LEVELS, gl.GL_RGBA16F, width, height)
            for name, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR),
                                (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                                (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                                (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE),
                                (gl.GL_TEXTURE_MAX_LEVEL, LEVELS - 1)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, name, value)
        self.depth = int(gl.glGenRenderbuffers(1))
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self.depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24,
                                 width, height)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, 0)
        previous = _bindings()
        self.framebuffer = int(gl.glGenFramebuffers(1))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, self.texture, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self.depth)
        gl.glDrawBuffers(1, [gl.GL_COLOR_ATTACHMENT0])
        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        _restore(previous)
        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            self.release()
            raise RuntimeError('the reflection atlas is incomplete (0x%x)' % int(status))
        self.size = (width, height)
        return True

    def _slot(self, rect: TileRect) -> TileRect:
        """``rect`` grown by the gutter each side, within the atlas."""
        x, y, width, height = rect
        x0, y0 = max(0, x - GUTTER), max(0, y - GUTTER)
        x1 = min(self.size[0], x + width + GUTTER)
        y1 = min(self.size[1], y + height + GUTTER)
        return x0, y0, max(0, x1 - x0), max(0, y1 - y0)

    def keep(self, tiles: Iterable[TileRect]) -> None:
        """Copy ``tiles`` of the atlas aside, each with its gutter, for the
        mirror views about to be drawn to read."""
        from OpenGL import GL as gl
        width, height = self.size
        previous = _bindings()
        if not self.kept:
            self.kept = int(gl.glGenTextures(1))
            with self._on_unit(self.kept):
                gl.glTexStorage2D(gl.GL_TEXTURE_2D, 1, gl.GL_RGBA16F, width, height)
                for name, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                                    (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                                    (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                                    (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                    gl.glTexParameteri(gl.GL_TEXTURE_2D, name, value)
            self._kept_framebuffer = int(gl.glGenFramebuffers(1))
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._kept_framebuffer)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, self.kept, 0)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.framebuffer)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self._kept_framebuffer)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        for x, y, w, h in {self._slot(tile) for tile in tiles}:
            if w and h:
                gl.glBlitFramebuffer(x, y, x + w, y + h, x, y, x + w, y + h,
                                     gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        _restore(previous)

    def bind_kept(self) -> None:
        """Put the copy :meth:`keep` made on :data:`REFLECTION_UNIT`."""
        self._bind_unit(self.kept)

    def begin(self) -> Bindings:
        """Draw into the atlas from here; answers the bindings to go back to."""
        from OpenGL import GL as gl
        previous = _bindings()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        self.mipmapped = False
        return previous

    def clear(self, rect: TileRect) -> None:
        """Clear one tile and its gutter to nothing: alpha 0, the far plane.

        The viewport is left on the tile, for its mirror view to draw in.
        """
        from OpenGL import GL as gl
        gl.glViewport(*rect)
        gl.glScissor(*self._slot(rect))
        colour = [float(value) for value in gl.glGetFloatv(gl.GL_COLOR_CLEAR_VALUE)]
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glClearColor(*colour)
        gl.glScissor(*rect)

    def end(self, previous: Bindings, mipmap: bool = False) -> None:
        """Stop drawing into the atlas, blurring its levels where ``mipmap``."""
        from OpenGL import GL as gl
        _restore(previous)
        if mipmap:
            with self._on_unit(self.texture):
                gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            self.mipmapped = True

    def bind(self) -> None:
        """Put the atlas on :data:`REFLECTION_UNIT` for the mirrors to read."""
        self._bind_unit(self.texture)

    def unbind(self) -> None:
        """Leave nothing on :data:`REFLECTION_UNIT`, while the atlas is drawn into.

        A program that could sample the texture it draws into makes a feedback
        loop, which GL leaves undefined.
        """
        self._bind_unit(0)

    def _bind_unit(self, texture: int) -> None:
        """Leave ``texture`` on :data:`REFLECTION_UNIT`, and unit 0 active."""
        from OpenGL import GL as gl
        gl.glActiveTexture(gl.GL_TEXTURE0 + self.UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    @contextlib.contextmanager
    def _on_unit(self, texture: int) -> Iterator[None]:
        """``texture`` bound on :data:`REFLECTION_UNIT` to be worked on, and
        what that unit held and which unit was active put back after."""
        from OpenGL import GL as gl
        active = int(gl.glGetIntegerv(gl.GL_ACTIVE_TEXTURE))
        gl.glActiveTexture(gl.GL_TEXTURE0 + self.UNIT)
        held = int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D))
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        try:
            yield
        finally:
            gl.glBindTexture(gl.GL_TEXTURE_2D, held)
            gl.glActiveTexture(active)

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
