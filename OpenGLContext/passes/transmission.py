"""KHR_materials_transmission support: backdrop capture + capability selection.

Transmission (glass) needs the opaque scene as a texture the transmissive shader
can sample at the refracted screen position. After the opaque geometry is drawn,
:class:`TransmissionBuffer` copies the colour buffer into a mipmapped texture
(the mip chain gives roughness-blurred / frosted transmission), which the PBR
fragment shader reads on unit :data:`TransmissionBuffer.UNIT`.

The full path costs a full-screen copy + mipmap generation per frame, so on a
software rasteriser (or by request) we fall back to a cheap alpha-blend
approximation instead -- see :func:`resolve_mode`.
"""
from __future__ import annotations

import math
import os
from typing import Optional

from OpenGL.GL import (
    GL_TEXTURE_2D, GL_TEXTURE0, GL_RGB8,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
    GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_CLAMP_TO_EDGE,
    GL_READ_BUFFER, GL_READ_FRAMEBUFFER, GL_READ_FRAMEBUFFER_BINDING,
    GL_COLOR_ATTACHMENT0,
    glGenTextures, glDeleteTextures, glBindTexture, glActiveTexture,
    glTexParameteri, glTexStorage2D, glCopyTexSubImage2D, glGenerateMipmap,
    glReadBuffer, glGetIntegerv,
)

# Transmission backdrop sampler unit, within the 16-unit budget;
# see the unit map in pbrpass.PBR_UNITS. Sits just above the material maps.
TRANSMISSION_UNIT = 12

_SOFTWARE = ('llvmpipe', 'softpipe', 'swrast', 'software')


def resolve_mode(renderer: str = '', requested: str = '') -> str:
    """Choose the transmission path: 'full', 'blend', or 'off'.

    ``requested`` is ``ContextDefinition.transmission``; 'auto' or empty falls
    back to ``OPENGLCONTEXT_TRANSMISSION`` and then to the renderer, which is
    full on real GPUs and blend on a software rasteriser.
    """
    env = (requested or '').strip().lower()
    if env in ('', 'auto'):
        env = os.environ.get('OPENGLCONTEXT_TRANSMISSION', '').strip().lower()
    if env in ('off', 'none', '0'):
        return 'off'
    if env in ('blend', 'fake'):
        return 'blend'
    if env in ('full', 'on', '1'):
        return 'full'
    r = (renderer or '').lower()
    if any(s in r for s in _SOFTWARE):
        return 'blend'
    return 'full'


class TransmissionBuffer(object):
    """A mipmapped colour texture holding the opaque backdrop for transmission."""

    UNIT = TRANSMISSION_UNIT

    def __init__(self) -> None:
        self.tex: Optional[int] = None
        self.w = 0
        self.h = 0
        self.levels = 1

    def ensure_size(self, w: int, h: int) -> bool:
        w, h = max(1, int(w)), max(1, int(h))
        if self.tex is not None and (w, h) == (self.w, self.h):
            return True
        if self.tex is not None:
            glDeleteTextures([self.tex])
            self.tex = None
        self.w, self.h = w, h
        self.levels = max(1, int(math.floor(math.log2(max(w, h)))) + 1)
        self.tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glTexStorage2D(GL_TEXTURE_2D, self.levels, GL_RGB8, w, h)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)
        return True

    def capture(self) -> None:
        """Copy the read framebuffer's *colour* attachment into the texture + mips.

        Explicitly reads COLOR_ATTACHMENT0: under MRT the current read buffer may
        be the object-id attachment, and copying that would capture pick ids as the
        transmission backdrop. The caller's read buffer is saved and
        restored. The copy assumes a linear (non-sRGB) colour FBO, so the RGB8
        backdrop is sampled and refracted in the same space the shader shades in.
        """
        from OpenGLContext.capture import presented_buffer

        prev_buffer = int(glGetIntegerv(GL_READ_BUFFER))
        read_fbo = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
        # COLOR_ATTACHMENT0 is only valid on a framebuffer object; the default
        # framebuffer holds the frame in the back buffer, or in the front one
        # where it has no back buffer -- an offscreen surface may have none, and
        # naming a buffer that is not there is GL_INVALID_OPERATION.  Only the
        # read binding is known to be the default framebuffer here, so that is
        # the one asked.
        glReadBuffer(
            GL_COLOR_ATTACHMENT0 if read_fbo != 0
            else presented_buffer(GL_READ_FRAMEBUFFER))
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 0, 0, self.w, self.h)
        glGenerateMipmap(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, 0)
        glReadBuffer(prev_buffer)

    def bind(self) -> None:
        glActiveTexture(GL_TEXTURE0 + self.UNIT)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glActiveTexture(GL_TEXTURE0)

    @property
    def max_lod(self) -> float:
        return float(self.levels - 1)

    def release(self) -> None:
        if self.tex is not None:
            try:
                glDeleteTextures([self.tex])
            except Exception:
                pass
            self.tex = None
