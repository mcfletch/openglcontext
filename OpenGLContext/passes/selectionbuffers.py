"""Selection framebuffers for colour-based picking.

Two self-contained GL resource classes used by :class:`SelectionMixin`
(:mod:`OpenGLContext.passes.selection`):

* :class:`SelectionFBO` — a small FBO covering only the pick region, used by the
  legacy per-pick render path to keep selection fill cost low.
* :class:`SelectionBufferFBO` — a full-resolution Multiple-Render-Target buffer
  that writes object ids alongside scene colour during the forward pass, so a
  pick resolves to a 1x1 readback instead of a whole extra render.

Neither class references the pass; they are pure GL-resource holders, so the
picking *logic* in :mod:`selection` stays free of framebuffer bookkeeping.
:mod:`selection` re-exports both names, so
``from OpenGLContext.passes.selection import SelectionBufferFBO`` resolves.
"""
from __future__ import annotations

from typing import Optional

from OpenGL.GL import *
from OpenGLContext.arrays import array
import logging

log = logging.getLogger(__name__)


class SelectionFBO:
    """Framebuffer Object for optimized selection rendering.

    Renders selection pass to a small FBO covering only the pick region,
    dramatically reducing pixel fill cost for selection operations.
    """

    def __init__(self, max_width: int = 512, max_height: int = 512):
        """Initialize the selection FBO.

        Args:
            max_width: Maximum width of the FBO texture
            max_height: Maximum height of the FBO texture
        """
        self.max_width = max_width
        self.max_height = max_height
        self.fbo = None
        self.color_texture = None
        self.depth_renderbuffer = None
        self.current_width = 0
        self.current_height = 0
        self._initialized = False

    def _ensure_initialized(self, width: int, height: int) -> bool:
        """Ensure FBO is created and sized appropriately.

        Returns True if FBO is ready, False if FBO creation failed.
        """
        # Clamp to max size
        width = min(width, self.max_width)
        height = min(height, self.max_height)

        if width <= 0 or height <= 0:
            return False

        # Check if we need to create or resize
        if self._initialized and width <= self.current_width and height <= self.current_height:
            return True

        # Clean up existing resources
        self._cleanup()

        try:
            # Create FBO
            self.fbo = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)

            # Create color texture
            self.color_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.color_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                GL_TEXTURE_2D, self.color_texture, 0
            )

            # Create depth renderbuffer
            self.depth_renderbuffer = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth_renderbuffer)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                GL_RENDERBUFFER, self.depth_renderbuffer
            )

            # Check framebuffer completeness
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Selection FBO incomplete: status=%s", status)
                self._cleanup()
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                return False

            self.current_width = width
            self.current_height = height
            self._initialized = True

            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return True

        except Exception as e:
            log.warning("Failed to create selection FBO: %s", e)
            self._cleanup()
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return False

    def _cleanup(self):
        """Clean up OpenGL resources."""
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None

        if self.color_texture is not None:
            try:
                glDeleteTextures([self.color_texture])
            except Exception:
                pass
            self.color_texture = None

        if self.depth_renderbuffer is not None:
            try:
                glDeleteRenderbuffers(1, [self.depth_renderbuffer])
            except Exception:
                pass
            self.depth_renderbuffer = None

        self._initialized = False
        self.current_width = 0
        self.current_height = 0

    def bind(self, region_x: int, region_y: int, region_width: int, region_height: int) -> bool:
        """Bind the FBO and set up viewport for the pick region.

        Args:
            region_x: Left edge of pick region in viewport coords
            region_y: Bottom edge of pick region in viewport coords
            region_width: Width of pick region
            region_height: Height of pick region

        Returns:
            True if FBO is bound and ready, False otherwise
        """
        if not self._ensure_initialized(region_width, region_height):
            return False

        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, region_width, region_height)
        return True

    def unbind(self):
        """Unbind the FBO and restore default framebuffer."""
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def read_pixel(self, local_x: int, local_y: int) -> int:
        """Read a pixel from the FBO.

        Args:
            local_x: X coordinate within the FBO (not viewport coords)
            local_y: Y coordinate within the FBO (not viewport coords)

        Returns:
            32-bit RGBA value as integer
        """
        pixel = array([0, 0, 0, 0], 'B')
        glReadPixels(local_x, local_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
        return int(pixel.view('<I')[0])


class SelectionBufferFBO:
    """Full-resolution selection buffer using Multiple Render Targets (MRT).

    Renders object IDs alongside normal scene color during the forward pass,
    enabling zero-cost pick event processing via CPU-side buffer lookup.

    The buffer contains:
    - Color attachment 0: Normal scene color (blitted to screen)
    - Color attachment 1: Object ID encoded as RGBA8

    After each frame, the ID buffer is read back to CPU memory, and pick
    events are resolved by simple array lookup with no GPU interaction.
    """

    def __init__(self):
        """Initialize the selection buffer (lazy GPU resource creation)."""
        self.fbo = None
        self.color_texture = None       # Normal scene color (attachment 0)
        self.id_texture = None          # Object ID buffer (attachment 1)
        self.depth_renderbuffer = None
        self.width = 0
        self.height = 0
        self._initialized = False

        # Object ID to path mapping (rebuilt each frame)
        self.id_map = {}

    def ensure_size(self, width: int, height: int) -> bool:
        """Ensure FBO is created and sized to match viewport.

        Args:
            width: Viewport width
            height: Viewport height

        Returns:
            True if FBO is ready, False on failure
        """
        width = int(width)
        height = int(height)

        if width <= 0 or height <= 0:
            return False

        # Check if already correct size
        if self._initialized and width == self.width and height == self.height:
            return True

        # Need to recreate at new size
        self._cleanup()

        try:
            # Create FBO
            self.fbo = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)

            # Create color texture (attachment 0) - normal scene color
            self.color_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.color_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                GL_TEXTURE_2D, self.color_texture, 0
            )

            # Create ID texture (attachment 1) - object IDs as RGBA8
            self.id_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.id_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                GL_TEXTURE_2D, self.id_texture, 0
            )

            # Create depth renderbuffer
            self.depth_renderbuffer = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth_renderbuffer)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                GL_RENDERBUFFER, self.depth_renderbuffer
            )

            # Set draw buffers for MRT
            glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])

            # Check framebuffer completeness
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Selection buffer FBO incomplete: status=%s", status)
                self._cleanup()
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                return False

            self.width = width
            self.height = height
            self._initialized = True

            # No full-framebuffer CPU mirror: picking reads 1x1 pixels on demand
            # from the FBO (read_pixel). A per-frame full-buffer readback both
            # stalls the GPU and, when allocated as array([0]*N), built a
            # multi-million-element Python list that froze the loop on large windows.
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            log.debug("Selection buffer FBO created: %dx%d", width, height)
            return True

        except Exception as e:
            log.warning("Failed to create selection buffer FBO: %s", e)
            self._cleanup()
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return False

    def _cleanup(self):
        """Clean up OpenGL resources."""
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None

        if self.color_texture is not None:
            try:
                glDeleteTextures([self.color_texture])
            except Exception:
                pass
            self.color_texture = None

        if self.id_texture is not None:
            try:
                glDeleteTextures([self.id_texture])
            except Exception:
                pass
            self.id_texture = None

        if self.depth_renderbuffer is not None:
            try:
                glDeleteRenderbuffers(1, [self.depth_renderbuffer])
            except Exception:
                pass
            self.depth_renderbuffer = None

        self._initialized = False
        self.width = 0
        self.height = 0

    def bind(self) -> bool:
        """Bind the FBO for rendering.

        Returns:
            True if bound successfully
        """
        if not self._initialized:
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        # Ensure both attachments are written to
        glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])
        return True

    def unbind(self):
        """Unbind the FBO."""
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def clear(self):
        """Clear both color attachments and depth buffer.

        Clears color attachment 0 to scene background (handled by caller)
        and color attachment 1 to zero (no object ID).
        """
        # Clear ID buffer to 0 (no object) - need to clear attachment 1 specifically
        # First clear depth
        glClear(GL_DEPTH_BUFFER_BIT)

        # Clear ID attachment to 0 by drawing to only that buffer
        glDrawBuffers(1, [GL_COLOR_ATTACHMENT1])
        glClearColor(0, 0, 0, 0)
        glClear(GL_COLOR_BUFFER_BIT)

        # Restore both draw buffers
        glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])

    def read_pixel(self, x: int, y: int):
        """Read (object_id, depth) at one pixel straight from the FBO.

        This replaces reading back the *entire* id+depth buffer every frame (a
        full-framebuffer glReadPixels that stalls the GPU and scales with window
        size). Picking only needs the pixels under the pick points, so we read
        1x1 on demand from the still-populated FBO (called at frame top, before
        this frame overwrites it).
        """
        if not self._initialized:
            return 0, 1.0
        x, y = int(x), int(y)
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return 0, 1.0
        prev = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo)
        try:
            glReadBuffer(GL_COLOR_ATTACHMENT1)
            px = array([0, 0, 0, 0], 'B')
            glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px)
            dz = array([0.0], 'f')
            glReadPixels(x, y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, dz)
        finally:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, prev)
        obj_id = int(px[0]) | (int(px[1]) << 8) | (int(px[2]) << 16) | (int(px[3]) << 24)
        return obj_id, float(dz[0])

    def blit_to_screen(self, target_width: int, target_height: int):
        """Blit the color buffer to the default framebuffer.

        Args:
            target_width: Screen width
            target_height: Screen height
        """
        if not self._initialized:
            return

        # Blit from our FBO to default framebuffer
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBlitFramebuffer(
            0, 0, self.width, self.height,
            0, 0, target_width, target_height,
            GL_COLOR_BUFFER_BIT,
            GL_NEAREST
        )

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def set_id_map(self, id_map: dict):
        """Set the object ID to path mapping for this frame."""
        self.id_map = id_map
