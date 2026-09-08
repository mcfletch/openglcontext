"""Shared framebuffer-capture helpers.

Reading the freshly rendered back buffer and writing it to a PNG was reimplemented
in half a dozen places (the auto-exit hook, the interactive save-image handler, the
regression harness, and several test capture runners). They all did the same thing:
``glReadBuffer(GL_BACK)`` + ``glReadPixels`` + a vertical flip (OpenGL is bottom-up)
+ a Pillow save. This module is the single home for that logic.

Capture the back buffer from :meth:`OpenGLContext.context.Context.presentFrame`,
before the swap: reading it *after* the swap returns an older frame.
"""
import logging
import os

import numpy as np
from OpenGL.GL import (
    glReadPixels, glReadBuffer, glGetIntegerv, glBindFramebuffer,
    glGetFramebufferAttachmentParameteriv,
    GL_VIEWPORT, GL_BACK, GL_FRONT, GL_RGB, GL_UNSIGNED_BYTE,
    GL_FRAMEBUFFER, GL_BACK_LEFT, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE, GL_NONE,
)

log = logging.getLogger(__name__)


def presented_buffer(target=GL_FRAMEBUFFER):
    """Which colour buffer of the default framebuffer holds the finished frame.

    target -- the binding point the default framebuffer is current on.  A
        caller that has it bound only for reading names ``GL_READ_FRAMEBUFFER``;
        the query is about whichever framebuffer is bound there, so the default
        one has to be.

    ``GL_BACK`` where the framebuffer has a back buffer, and ``GL_FRONT`` where
    it does not -- a surface nothing presents may carry a single colour buffer,
    and naming a buffer that is not there is ``GL_INVALID_OPERATION`` rather
    than a quiet fallback, in either direction.

    The framebuffer is asked which buffers it *has*, rather than asked whether
    it is double buffered.  Those are different questions: an EGL window
    surface reports ``GL_DOUBLEBUFFER`` false and still keeps its one colour
    buffer in ``GL_BACK``, with no front buffer to read at all.
    """
    attachment = glGetFramebufferAttachmentParameteriv(
        target, GL_BACK_LEFT, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE)
    return GL_FRONT if int(attachment) == GL_NONE else GL_BACK


def ensure_pillow():
    """Return the Pillow ``Image`` module, or None (with a warning) if unavailable."""
    try:
        from PIL import Image
        return Image
    except ImportError:
        log.warning("Pillow not available, image saving disabled")
        return None


def read_back_buffer(hud_height=0):
    """Read the current back buffer as a top-down RGB uint8 array.

    hud_height -- pixels to drop from the *bottom* of the frame (where the HUD /
        frame-rate counter is drawn), so regression captures ignore it.

    Returns ``(pixels, width, height)`` where ``pixels`` has shape
    ``(height, width, 3)`` and is already flipped to top-down image order.
    """
    _vx, _vy, vp_width, vp_height = (int(v) for v in glGetIntegerv(GL_VIEWPORT))
    y = hud_height if hud_height > 0 else 0
    height = max(1, vp_height - hud_height) if hud_height > 0 else vp_height
    width = vp_width

    # Read the on-screen result. Bind the default framebuffer first: a post-process
    # pass (bloom) may leave its own FBO bound, and naming a default-framebuffer
    # colour buffer is invalid unless the default framebuffer is current.
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glReadBuffer(presented_buffer())
    raw = glReadPixels(0, y, width, height, GL_RGB, GL_UNSIGNED_BYTE)
    pixels = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)).copy()
    return pixels, width, height


def save_png(filepath, pixels):
    """Save a top-down RGB uint8 array to ``filepath`` as PNG. Returns success bool."""
    if pixels is None:
        log.error("No pixels to save")
        return False
    Image = ensure_pillow()
    if Image is None:
        return False
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    Image.fromarray(pixels, mode='RGB').save(filepath)
    return True


def capture_to_png(filepath, hud_height=0, skip_blank=True):
    """Read the back buffer and save it to ``filepath``.

    skip_blank -- when True, an all-black frame is not written (the renderer often
        produces a blank first frame; callers that save every frame want the last
        good one to survive). Returns True only when a file was written.
    """
    try:
        pixels, _w, _h = read_back_buffer(hud_height)
    except Exception as err:  # pragma: no cover - diagnostic only
        log.warning("back-buffer read failed: %r", err)
        return False
    if skip_blank and not pixels.any():
        return False
    return save_png(filepath, pixels)


class SettleCapture:
    """Capture once the scene has settled, then signal the caller to exit.

    Some renderers (e.g. the analytic-sky IBL) take several frames to converge, so a
    single-frame capture reads wrong. A caller drives this from its ``presentFrame``:
    it calls :meth:`tick` every frame and, once both the wall-clock delay and the
    minimum frame count are satisfied, ``tick`` captures to ``path`` and returns True
    so the caller can quit. ``delay`` is a floor on time, ``min_frames`` a floor on
    frames -- whichever is longer wins.
    """

    def __init__(self, path, delay=0.0, min_frames=1, hud_height=0):
        self.path = path
        self.delay = float(delay)
        self.min_frames = max(1, int(min_frames))
        self.hud_height = hud_height
        self._frames = 0
        self._start = None
        self.done = False

    def tick(self):
        """Advance one frame; capture + return True when settled, else False."""
        if self.done:
            return False
        # perf_counter is imported lazily so importing this module never touches a
        # clock (keeps it safe for deterministic/replayable environments).
        from time import perf_counter
        if self._start is None:
            self._start = perf_counter()
        self._frames += 1
        if self._frames < self.min_frames:
            return False
        if perf_counter() - self._start < self.delay:
            return False
        save_png(self.path, read_back_buffer(self.hud_height)[0])
        self.done = True
        return True
