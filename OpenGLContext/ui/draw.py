"""Drawing the overlay: one small program, one batch, as few draws as possible.

Everything an overlay puts on screen is a coloured quad, textured or not -- a
panel's fill, a button's frame, a nine-slice from a game's artwork, a glyph from
the shader font's atlas.  So there is one program here that draws exactly that,
and the widgets describe themselves to it through :meth:`Widget.paint` rather
than any of them knowing what GL is.

Quads accumulate into one buffer and are flushed only when the state that
cannot vary per vertex changes: the texture, the blend mode (the focus glow is
additive) and the scissor rectangle (a scroll viewport clips with one).  A
whole settings page is normally two or three draws.

The alpha-mask flag *is* per vertex, so text and frames batch together whenever
they share a texture: the font atlas carries coverage in its alpha channel,
while a skin's artwork is modulated in full colour.

Round shapes -- the knob of a switch, the ends of its track -- come from one
small disc generated here at start-up rather than from artwork.  A game that
ships no assets at all still gets a switch with round ends, and the shape stays
smooth at any interface scale because it is sampled, not rasterised into a
fixed-size image.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ctypes

from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CLAMP_TO_EDGE, GL_CULL_FACE, GL_DEPTH_TEST,
    GL_DYNAMIC_DRAW, GL_FLOAT, GL_FALSE, GL_FRAGMENT_SHADER, GL_LINEAR,
    GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_RGBA, GL_RGBA8, GL_SCISSOR_TEST,
    GL_SRC_ALPHA, GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TRIANGLES,
    GL_UNSIGNED_BYTE, GL_VERTEX_SHADER,
    glActiveTexture, glBindBuffer, glBindTexture, glBindVertexArray,
    glBlendFunc, glBufferData, glDeleteBuffers, glDeleteTextures,
    glDeleteVertexArrays, glDisable, glDrawArrays, glEnable,
    glEnableVertexAttribArray, glGenBuffers, glGenTextures, glGenVertexArrays,
    glGetUniformLocation, glScissor, glTexImage2D, glTexParameteri,
    glUniform1i, glUniform2f, glUseProgram, glVertexAttribPointer,
)
from OpenGL.GL import shaders as GL_shaders

import numpy as np

from OpenGLContext.ui.geometry import Rect

log = logging.getLogger(__name__)

__all__ = ['OverlayRenderer']

#: Floats per vertex: x, y, u, v, r, g, b, a, mask.
_STRIDE = 9
#: Side of the generated disc texture.  Large enough that a knob drawn at any
#: interface scale samples it up rather than down, small enough to be free.
_DISC_SIZE = 64

_VERTEX = """#version 330 core
layout(location = 0) in vec2 aPosition;   // pixels, bottom-left origin
layout(location = 1) in vec2 aTexCoord;
layout(location = 2) in vec4 aColor;
layout(location = 3) in float aMask;      // 1 = sample alpha only (glyphs)
uniform vec2 viewport;
out vec2 vTexCoord;
out vec4 vColor;
out float vMask;
void main(){
    vTexCoord = aTexCoord;
    vColor = aColor;
    vMask = aMask;
    gl_Position = vec4(aPosition / viewport * 2.0 - 1.0, 0.0, 1.0);
}"""

_FRAGMENT = """#version 330 core
in vec2 vTexCoord;
in vec4 vColor;
in float vMask;
uniform sampler2D image;
out vec4 fragColor;
void main(){
    vec4 texel = texture(image, vTexCoord);
    // A glyph carries coverage in alpha only; artwork modulates in full colour.
    fragColor = mix(vColor * texel, vec4(vColor.rgb, vColor.a * texel.a), vMask);
}"""


def _rgba(colour: Any) -> Tuple[float, float, float, float]:
    """Four floats from a colour field, tolerating a three-component one."""
    values = [float(component) for component in colour]
    while len(values) < 4:
        values.append(1.0)
    return (values[0], values[1], values[2], values[3])


def _disc_coverage(size: int) -> bytes:
    """A white RGBA square whose alpha is the coverage of an inscribed circle.

    The edge is softened over a couple of texels so the shape stays clean when
    it is sampled up to a knob several times this size, which is what a 4K
    display asks for.
    """
    centre = (size - 1) / 2.0
    radius = size / 2.0
    rows, columns = np.mgrid[0:size, 0:size]
    distance = np.hypot(columns - centre, rows - centre)
    softness = max(1.0, size / 32.0)
    alpha = np.clip((radius - distance) / softness, 0.0, 1.0)
    image = np.empty((size, size, 4), dtype=np.uint8)
    image[..., :3] = 255
    image[..., 3] = (alpha * 255).astype(np.uint8)
    return image.tobytes()


class OverlayRenderer:
    """Draws an overlay stack with one program and one vertex buffer."""

    #: Blend modes a quad can be drawn in.
    BLEND, ADD = 'blend', 'add'

    def __init__(self, font_size: int = 16) -> None:
        self.font_size = font_size
        self.metrics: Any = None
        self.skin: Any = None
        self._program: Any = None
        self._vao: Any = None
        self._vbo: Any = None
        self._white: Any = None
        self._disc: Any = None
        self._text: Any = None
        self._images: Dict[str, Any] = {}
        self._vertices: List[float] = []
        self._texture: Any = None
        self._mode: str = self.BLEND
        self._scissor: Optional[Rect] = None
        self._viewport: Tuple[int, int] = (1, 1)

    # -- lifecycle --------------------------------------------------------
    @classmethod
    def forContext(cls, context: Any, font_size: int = 16
                   ) -> Optional['OverlayRenderer']:
        """The renderer for one context, made on first use.

        Per context rather than per process: a GL object belongs to the context
        it was made in, and two windows would otherwise share one buffer id.
        Asking for a different font size re-points the same renderer at another
        atlas rather than building a second one, since the window growing is
        exactly when that happens.
        """
        renderer = getattr(context, '_overlayRenderer', None)
        if renderer is None:
            renderer = cls(font_size)
            context._overlayRenderer = renderer
        elif renderer.font_size != font_size:
            renderer.useFontSize(font_size)
        if not renderer.initialize():
            return None
        return renderer

    def useFontSize(self, font_size: int) -> None:
        """Draw with another atlas from here on.

        The program, buffers and generated textures are unaffected; only the
        glyphs and the measurements taken from them change.
        """
        self.font_size = int(font_size)
        self._text = None
        self.metrics = None

    def initialize(self) -> bool:
        """Build the program, the buffers and the font; False if any refuses.

        The two halves are separate because the font is the one that changes
        while the renderer lives: the window grows, the interface scale with
        it, and another atlas is wanted for GL objects that are still perfectly
        good.
        """
        if self._program is None and not self._buildProgram():
            return False
        return self._text is not None or self._buildFont()

    def _buildProgram(self) -> bool:
        """Compile the shader and make the buffers and generated textures."""
        try:
            self._program = GL_shaders.compileProgram(
                GL_shaders.compileShader(_VERTEX, GL_VERTEX_SHADER),
                GL_shaders.compileShader(_FRAGMENT, GL_FRAGMENT_SHADER),
                validate=False,
            )
            self._vao = glGenVertexArrays(1)
            self._vbo = glGenBuffers(1)
            self._white = self._uploadTexture(1, 1, b'\xff\xff\xff\xff')
            self._disc = self._uploadTexture(_DISC_SIZE, _DISC_SIZE,
                                             _disc_coverage(_DISC_SIZE))
        except Exception:                       # pragma: no cover - driver
            log.warning("overlay renderer unavailable", exc_info=True)
            self._program = None
            return False
        return True

    def _buildFont(self) -> bool:
        """Point the renderer at the atlas for its font size, and measure it."""
        from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
        from OpenGLContext.ui.metrics import metrics_for
        try:
            text = get_text_renderer(self.font_size)
            if not text.initialize() or not text.char_width:
                return False
        except Exception:                       # pragma: no cover - driver
            log.warning("overlay font unavailable", exc_info=True)
            return False
        self._text = text
        self.metrics = metrics_for(text)
        return True

    def close(self) -> None:
        """Release the GL objects.  Only useful when a context goes away."""
        for deleter, value in ((glDeleteVertexArrays, self._vao),
                               (glDeleteBuffers, self._vbo)):
            if value is not None:
                deleter(1, [value])
        # ``_images`` holds (texture, width, height), and () for a file that
        # would not load, so the ids have to be picked out rather than passed
        # as they are stored.
        alive = [int(entry[0]) for entry in self._images.values() if entry]
        for generated in (self._white, self._disc):
            if generated is not None:
                alive.append(int(generated))
        if alive:
            glDeleteTextures(len(alive), alive)
        self._vao = self._vbo = self._white = self._program = None
        self._disc = None
        self._images = {}

    @staticmethod
    def _uploadTexture(width: int, height: int, data: bytes) -> Any:
        texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        # Clamped, not repeated: a nine-slice edge sampled past its border
        # would otherwise wrap round and show the opposite corner.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, data)
        glBindTexture(GL_TEXTURE_2D, 0)
        return texture

    def imageTexture(self, url: str) -> Optional[Tuple[Any, int, int]]:
        """A skin image's texture, size included, loaded once and kept.

        Returns None when the file cannot be read, so a missing skin asset
        degrades to the flat fill rather than taking the frame down.
        """
        cached = self._images.get(url)
        if cached is not None:
            return cached if cached != () else None
        try:
            from PIL import Image
            image = Image.open(url).convert('RGBA')
            width, height = image.size
            entry = (self._uploadTexture(width, height, image.tobytes()),
                     width, height)
        except Exception:
            log.warning("could not load overlay skin image %s", url,
                        exc_info=True)
            self._images[url] = ()              # remembered, so we try once
            return None
        self._images[url] = entry
        return entry

    # -- the batch --------------------------------------------------------
    def _state(self, texture: Any, mode: str) -> None:
        if texture is not self._texture or mode != self._mode:
            self.flush()
            self._texture = texture
            self._mode = mode

    def quad(self, rect: Rect, colour: Any, uv: Sequence[float] = (0, 0, 1, 1),
             texture: Any = None, mask: float = 0.0,
             mode: str = BLEND) -> None:
        """Add one quad to the batch."""
        if rect.empty:
            return
        self._state(self._white if texture is None else texture, mode)
        red, green, blue, alpha = _rgba(colour)
        if alpha <= 0:
            return
        x0, y0 = float(rect.x), float(rect.y)
        x1, y1 = float(rect.right), float(rect.top)
        u0, v0, u1, v1 = (float(value) for value in uv)
        corners = ((x0, y0, u0, v0), (x1, y0, u1, v0), (x1, y1, u1, v1),
                   (x0, y0, u0, v0), (x1, y1, u1, v1), (x0, y1, u0, v1))
        for x, y, u, v in corners:
            self._vertices.extend((x, y, u, v, red, green, blue, alpha, mask))

    def flush(self) -> None:
        """Draw whatever has accumulated."""
        if not self._vertices:
            return
        data = np.array(self._vertices, dtype='f')
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
        stride = _STRIDE * 4
        for index, size, offset in ((0, 2, 0), (1, 2, 8), (2, 4, 16), (3, 1, 32)):
            glEnableVertexAttribArray(index)
            glVertexAttribPointer(index, size, GL_FLOAT, GL_FALSE, stride,
                                  ctypes.c_void_p(offset))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D,
                      self._white if self._texture is None else self._texture)
        if self._mode == self.ADD:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        else:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDrawArrays(GL_TRIANGLES, 0, len(self._vertices) // _STRIDE)
        self._vertices = []

    # -- primitives the widgets use ---------------------------------------
    def rect(self, rect: Rect, colour: Any) -> None:
        """A flat translucent rectangle."""
        self.quad(rect, colour)

    def glow(self, rect: Rect, colour: Any) -> None:
        """The focus ring: additive, and outside the widget's own rectangle."""
        self.quad(rect, colour, mode=self.ADD)

    def disc(self, rect: Rect, colour: Any) -> None:
        """A circle inscribed in a rectangle -- a switch's knob."""
        if rect.empty:
            return
        self.quad(rect, colour, (0, 0, 1, 1), texture=self._disc, mask=1.0)

    def pill(self, rect: Rect, colour: Any) -> None:
        """A rectangle with semicircular ends -- a switch's track.

        Three quads off the one disc: its left half, its right half, and a
        single column from its middle stretched across the straight part.  That
        column is opaque except where the circle's top and bottom edges fall,
        which is exactly the antialiasing the straight edges want, and using
        the same texture keeps the whole switch in the same batch as the text
        around it.
        """
        if rect.empty:
            return
        radius = min(rect.height // 2, rect.width // 2)
        if radius <= 0:
            self.rect(rect, colour)
            return
        self.quad(Rect(rect.x, rect.y, radius, rect.height), colour,
                  (0, 0, 0.5, 1), texture=self._disc, mask=1.0)
        self.quad(Rect(rect.right - radius, rect.y, radius, rect.height),
                  colour, (0.5, 0, 1, 1), texture=self._disc, mask=1.0)
        middle = Rect(rect.x + radius, rect.y,
                      rect.width - radius * 2, rect.height)
        self.quad(middle, colour, (0.5, 0, 0.5, 1), texture=self._disc,
                  mask=1.0)

    def border(self, rect: Rect, colour: Any, width: int = 1) -> None:
        """A hairline frame, drawn as four thin rectangles."""
        if width <= 0 or rect.empty:
            return
        self.rect(Rect(rect.x, rect.y, rect.width, width), colour)
        self.rect(Rect(rect.x, rect.top - width, rect.width, width), colour)
        self.rect(Rect(rect.x, rect.y, width, rect.height), colour)
        self.rect(Rect(rect.right - width, rect.y, width, rect.height), colour)

    def frame(self, rect: Rect, colour: Any, image: Any = None) -> None:
        """A widget's body: its artwork if it has any, else a flat fill."""
        if image is not None and self.ninepatch(rect, image):
            return
        self.rect(rect, colour)

    def ninepatch(self, rect: Rect, image: Any) -> bool:
        """Draw a nine-slice into a rectangle.  False if it cannot be drawn.

        Four corners at their own size, four edges stretched along one axis and
        the centre stretched along both -- which is what lets one button image
        serve every button width instead of one image per label.
        """
        urls = [str(url) for url in getattr(image, 'url', ()) if url]
        if not urls or rect.empty:
            return False
        entry = self.imageTexture(urls[0])
        if entry is None:
            return False
        texture, source_w, source_h = entry
        left, top, right, bottom = image.borders()
        # A border wider than the destination would make the middle negative,
        # so the corners are squeezed to fit rather than overlapping.
        left, right = self._fit(left, right, rect.width)
        top, bottom = self._fit(top, bottom, rect.height)
        columns = self._spans(rect.x, rect.width, left, right, source_w, 0)
        rows = self._spans(rect.y, rect.height, bottom, top, source_h, 1)
        tint = _rgba(image.tint)
        for x, width, u0, u1 in columns:
            for y, height, v0, v1 in rows:
                self.quad(Rect(x, y, width, height), tint, (u0, v0, u1, v1),
                          texture=texture)
        return True

    @staticmethod
    def _fit(near: int, far: int, available: int) -> Tuple[int, int]:
        total = near + far
        if total <= available or total <= 0:
            return (near, far)
        return (near * available // total, far * available // total)

    @staticmethod
    def _spans(start: int, extent: int, near: int, far: int, source: int,
               flip: int) -> List[Tuple[int, int, float, float]]:
        """Three (offset, size, uv near, uv far) runs along one axis.

        ``flip`` is set for the vertical axis, where the image's first row is
        the top but the screen's first pixel is the bottom.
        """
        middle = max(0, extent - near - far)
        sizes = [near, middle, far]
        source_sizes = [near, max(0, source - near - far), far]
        spans = []
        offset = start
        source_offset = 0
        for size, source_size in zip(sizes, source_sizes, strict=True):
            if size > 0 and source:
                low = source_offset / float(source)
                high = (source_offset + source_size) / float(source)
                if flip:
                    spans.append((offset, size, 1.0 - low, 1.0 - high))
                else:
                    spans.append((offset, size, low, high))
            offset += size
            source_offset += source_size
        return spans

    def text(self, text: str, x: int, y: int, colour: Any) -> None:
        """One line of text, with ``y`` the bottom of the character cell."""
        if not text or self._text is None:
            return
        char_w = self._text.char_width
        char_h = self._text.char_height
        cursor = x
        for character in text:
            u0, v0, u1, v1 = self._text.glyph_uv(character)
            self.quad(Rect(cursor, y, char_w, char_h), colour, (u0, v0, u1, v1),
                      texture=self._text.texture, mask=1.0)
            cursor += char_w

    def textIn(self, rect: Rect, text: str, colour: Any, align: str = 'left',
               pad: int = 0) -> None:
        """One line of text placed in a rectangle, centred vertically."""
        if not text:
            return
        width = self.metrics.text_width(text)
        if align == 'center':
            x = rect.x + (rect.width - width) // 2
        elif align == 'right':
            x = rect.right - width - pad
        else:
            x = rect.x + pad
        y = rect.y + (rect.height - self.metrics.char_height) // 2
        self.text(text, x, y, colour)

    def lines(self, rect: Rect, lines: Sequence[str], colour: Any,
              align: str = 'left') -> None:
        """Several lines, top-down from the top of the rectangle."""
        top = rect.top - self.metrics.char_height
        for index, line in enumerate(lines):
            row = Rect(rect.x, top - index * self.metrics.line_height,
                       rect.width, self.metrics.char_height)
            if row.top < rect.y:
                break
            self.textIn(row, line, colour, align=align)

    # -- clipping ---------------------------------------------------------
    def pushScissor(self, rect: Rect) -> Optional[Rect]:
        """Clip to a rectangle, intersected with whatever already clips."""
        self.flush()
        previous = self._scissor
        clipped = rect if previous is None else rect.clip(previous)
        self._scissor = clipped
        glEnable(GL_SCISSOR_TEST)
        glScissor(clipped.x, clipped.y, max(0, clipped.width),
                  max(0, clipped.height))
        return previous

    def popScissor(self, previous: Optional[Rect]) -> None:
        """Restore the clip a matching :meth:`pushScissor` returned."""
        self.flush()
        self._scissor = previous
        if previous is None:
            glDisable(GL_SCISSOR_TEST)
        else:
            glScissor(previous.x, previous.y, max(0, previous.width),
                      max(0, previous.height))

    # -- the frame --------------------------------------------------------
    def begin(self, viewport: Tuple[int, int]) -> bool:
        """Make the overlay program current and set the screen-space state.

        Public so a game can draw its own HUD into the same batch rather than
        standing up a second program for a handful of quads.  Every call must
        be matched by :meth:`end`.
        """
        width, height = int(viewport[0]), int(viewport[1])
        if not width or not height or not self.initialize():
            return False
        self._viewport = (width, height)
        glUseProgram(self._program)
        glUniform2f(glGetUniformLocation(self._program, 'viewport'),
                    float(width), float(height))
        glUniform1i(glGetUniformLocation(self._program, 'image'), 0)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        glEnable(GL_BLEND)
        self._texture = None
        self._mode = self.BLEND
        self._scissor = None
        return True

    def end(self) -> None:
        """Draw what is left and put the GL state back as it was found."""
        try:
            self.flush()
        finally:
            glDisable(GL_SCISSOR_TEST)
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_BLEND)
            glEnable(GL_DEPTH_TEST)
            glUseProgram(0)

    def draw(self, stack: Any, viewport: Tuple[int, int]) -> None:
        """Draw every panel in the stack, oldest first so the newest is on top."""
        if not self.begin(viewport):
            return
        width, height = self._viewport
        try:
            for panel in stack.panels:
                self.skin = panel.activeSkin()
                if panel.scrim:
                    self.rect(Rect(0, 0, width, height), self.skin.scrimFill)
                panel.paintTree(self)
        finally:
            self.end()
