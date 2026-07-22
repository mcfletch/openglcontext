"""Shader-based bitmap fonts using texture atlas.

This module provides a font provider that uses pre-rendered texture atlases
for text rendering, compatible with OpenGL core profile where GLUT bitmap
fonts and display lists are not available.

This serves as a fallback when glutfont is not available (non-GLUT contexts).
"""
from OpenGL.GL import *
from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGLContext.arrays import array
import numpy as np
import logging
import io

log = logging.getLogger(__name__)


class ShaderBitmapFont(font.NoDepthBufferMixIn, font.Font):
    """Shader-based bitmap font using texture atlas.

    This font renders text using textured quads with a pre-rendered
    font atlas, compatible with OpenGL core profile.
    """

    def __init__(self, fontStyle=None, size=16):
        """Initialize the shader bitmap font.

        Args:
            fontStyle: VRML FontStyle node (optional)
            size: Font size in pixels
        """
        self.fontStyle = fontStyle
        self._size = size
        self._displayLists = {}  # Cache for character metrics
        self._initialized = False
        self._texture = None
        self._atlas_module = None

        # Atlas parameters (will be set from module)
        self._char_width = 0
        self._char_height = 0
        self._atlas_width = 0
        self._atlas_height = 0
        self._first_char = 32
        self._last_char = 126
        self._chars_per_row = 16

    def _ensure_initialized(self):
        """Lazily initialize the font texture."""
        if self._initialized:
            return True

        try:
            from OpenGLContext.scenegraph.text import fonts
            actual_size, module = fonts.get_closest_atlas(self._size)
            if module is None:
                log.error("No font atlas available")
                return False

            self._atlas_module = module
            self._char_width = module.char_width
            self._char_height = module.char_height
            self._atlas_width = module.atlas_width
            self._atlas_height = module.atlas_height
            self._first_char = module.first_char
            self._last_char = module.last_char
            self._chars_per_row = module.chars_per_row

            # Create texture
            png_data = module.get_png_data()
            from PIL import Image
            img = Image.open(io.BytesIO(png_data))
            img = img.convert('RGBA')
            texture_data = np.array(img, dtype=np.uint8)

            self._texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self._texture)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA,
                self._atlas_width, self._atlas_height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE,
                texture_data.tobytes()
            )
            glBindTexture(GL_TEXTURE_2D, 0)

            self._initialized = True
            return True
        except Exception as e:
            log.error("Failed to initialize shader font: %s", e)
            return False

    def createChar(self, char, mode=None):
        """Create metrics for a character.

        Note: Unlike GLUT fonts, we don't use display lists.
        We just store the metrics for width calculation.
        """
        self._ensure_initialized()
        metrics = font.CharacterMetrics(
            char,
            self._char_width,
            self._char_height
        )
        # Return None for display list (we don't use them) and metrics
        return None, metrics

    def lists(self, value, mode=None):
        """Get display lists for value.

        For shader fonts, we don't use display lists.
        Return empty list - actual rendering is done differently.
        """
        return []

    def lineHeight(self, mode=None):
        """Get the line height for this font."""
        self._ensure_initialized()
        return int(self._char_height * 1.2)

    def render(self, lines, fontStyle=None, mode=None):
        """Render text lines.

        For shader-based rendering, we need to use the shader pipeline.
        """
        if not self._ensure_initialized():
            return

        if isinstance(lines, (bytes, str)):
            lines = self.toLines(lines, mode=mode)

        if fontStyle is None:
            fontStyle = self.fontStyle

        # Check if we're in shader mode
        shader_mode = getattr(mode, 'shader_mode', False)
        shader_program = getattr(mode, 'shader_program', None)

        if shader_mode and shader_program:
            self._render_shader(lines, fontStyle, mode, shader_program)
        else:
            # Legacy fallback - try to use glRasterPos/glBitmap style
            self._render_legacy(lines, fontStyle, mode)

    def _render_shader(self, lines, fontStyle, mode, shader_program):
        """Render using shader pipeline."""
        from OpenGLContext.scenegraph.text.shadertext import get_text_renderer

        # Get viewport for coordinate conversion
        viewport = getattr(mode, 'viewport', None)
        if viewport is None:
            return

        viewport_width = viewport[2]
        viewport_height = viewport[3]

        # Calculate text position - we need to convert from model space
        # For now, render at a fixed screen position
        # TODO: proper model-to-screen coordinate conversion

        text = '\n'.join(line.base for line in lines)
        renderer = get_text_renderer(self._char_height)

        # Render at bottom-left with some margin
        renderer.render_text(
            text, 10, 30, shader_program,
            viewport_width, viewport_height,
            color=(1.0, 1.0, 1.0, 1.0)
        )

    def _render_legacy(self, lines, fontStyle, mode):
        """Render using legacy OpenGL (compatibility mode).

        This uses glRasterPos and textured quads for each character.
        """
        if not self._texture:
            return

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self._texture)
        # Modulate so the glyph alpha drives blending. Scene geometry (e.g.
        # textured Shapes) may leave the env mode as GL_DECAL, which discards
        # the texture alpha and renders solid opaque cells instead of glyphs.
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)

        try:
            spacing = self.getSpacing(fontStyle=fontStyle, mode=mode)
            adjust = self.verticalAdjust(spacing, lines, fontStyle=fontStyle, mode=mode)

            glPushMatrix()
            glTranslatef(0, adjust, 0)

            for line in lines:
                height = line.height * spacing if fontStyle else line.height

                glPushMatrix()
                for char in line.base:
                    self._draw_char_quad(char)
                glPopMatrix()

                glTranslatef(0, -height, 0)

            glPopMatrix()
        finally:
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_BLEND)

    def _draw_char_quad(self, char):
        """Draw a single character as a textured quad."""
        char_code = ord(char)
        if char_code < self._first_char or char_code > self._last_char:
            char_code = ord('?')

        char_idx = char_code - self._first_char
        col = char_idx % self._chars_per_row
        row = char_idx // self._chars_per_row

        # Texture coordinates
        u0 = col * self._char_width / self._atlas_width
        u1 = (col + 1) * self._char_width / self._atlas_width
        v0 = row * self._char_height / self._atlas_height
        v1 = (row + 1) * self._char_height / self._atlas_height

        # Draw quad
        w = self._char_width
        h = self._char_height

        glBegin(GL_QUADS)
        glTexCoord2f(u0, v1); glVertex2f(0, 0)
        glTexCoord2f(u1, v1); glVertex2f(w, 0)
        glTexCoord2f(u1, v0); glVertex2f(w, h)
        glTexCoord2f(u0, v0); glVertex2f(0, h)
        glEnd()

        glTranslatef(w, 0, 0)

    def leftJustify(self, lines, fontStyle, mode=None):
        """Left-justify text."""
        self.render(lines, fontStyle, mode)

    def centerJustify(self, lines, fontStyle, mode=None):
        """Center-justify text."""
        # TODO: proper center justification
        self.render(lines, fontStyle, mode)

    def rightJustify(self, lines, fontStyle, mode=None):
        """Right-justify text."""
        # TODO: proper right justification
        self.render(lines, fontStyle, mode)


class _ShaderFontProvider(fontprovider.FontProvider):
    """Font provider using shader-based texture atlas fonts.

    This provider creates ShaderBitmapFont instances as a fallback
    when GLUT fonts are not available, and is required for core profile
    contexts where legacy GL functions are not available.
    """
    format = "bitmap"
    shader_compatible = True  # Mark as compatible with core profile/shader mode
    scale = 12  # Points to pixels

    # Available sizes from font atlas
    available_sizes = [12, 16, 24, 32, 48]

    def create(self, fontStyle, mode=None):
        """Create a new font for the given fontStyle and mode."""
        size = self._get_size(fontStyle)

        # Check for existing font
        fontHash = ('shader', size)
        if fontHash in self.fonts:
            current = self.fonts.get(fontHash)
            self.addFont(fontStyle, current)
            return current

        # Create new font
        shaderFont = ShaderBitmapFont(fontStyle, size=size)
        self.addFont(fontStyle, shaderFont)
        self.fonts[fontHash] = shaderFont
        return shaderFont

    def _get_size(self, fontStyle):
        """Get appropriate font size for fontStyle."""
        if fontStyle and hasattr(fontStyle, 'size'):
            target = int(fontStyle.size * self.scale)
        else:
            target = 12

        # Find closest available size
        diffs = [abs(target - s) for s in self.available_sizes]
        best_idx = diffs.index(min(diffs))
        return self.available_sizes[best_idx]

    def key(self, fontStyle=None):
        """Calculate font key for caching."""
        if not fontStyle:
            return None
        return (
            tuple(fontStyle.family) if fontStyle.family else (),
            fontStyle.size,
        )

    def enumerate(self, mode=None):
        """Enumerate available fonts."""
        return ['SANS', 'SERIF', 'TYPEWRITER']


# Create singleton provider
ShaderFontProvider = _ShaderFontProvider()


def register():
    """Register the shader font provider.

    Call this to make shader fonts available as a bitmap font provider.
    """
    ShaderFontProvider.registerProvider(ShaderFontProvider)


def is_available():
    """Check if shader fonts are available (font atlas exists)."""
    try:
        from OpenGLContext.scenegraph.text import fonts
        _, module = fonts.get_closest_atlas(16)
        return module is not None
    except ImportError:
        return False


# Auto-register if font atlases are available
if is_available():
    register()
