"""Shader-based text rendering for OpenGL 3.3+ core profile.

This module provides text rendering using texture atlases and shaders,
compatible with OpenGL core profile where display lists, glRasterPos,
and glBitmap are not available.

Uses pre-rendered DejaVu Sans Mono font atlases at multiple sizes.
"""
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
import numpy as np
import ctypes
import io
import logging

log = logging.getLogger(__name__)


class ShaderTextRenderer:
    """Shader-based text renderer for core profile OpenGL.

    Uses pre-rendered texture atlases from the fonts subpackage,
    rendering text with textured quads via VAO/VBO.

    Supports two rendering modes:
    - Transparent background: Text is rendered with alpha blending
    - Solid background: Text is rendered on a solid color background
    """

    def __init__(self, font_size=16):
        """Initialize the text renderer.

        Args:
            font_size: Desired font size in pixels. The closest available
                      size from the pre-rendered atlases will be used.
        """
        self._requested_size = font_size
        self._texture = None
        self._vao = None
        self._vbo = None
        self._initialized = False
        self._atlas_module = None

        # These will be set from the atlas module
        self._char_width = 0
        self._char_height = 0
        self._atlas_width = 0
        self._atlas_height = 0
        self._first_char = 32
        self._last_char = 126
        self._chars_per_row = 16
        self._actual_size = 0

    def _load_atlas_module(self):
        """Load the appropriate font atlas module."""
        try:
            from OpenGLContext.scenegraph.text import fonts
            actual_size, module = fonts.get_closest_atlas(self._requested_size)
            if module is None:
                log.error("No font atlas available")
                return False

            self._atlas_module = module
            self._actual_size = actual_size
            self._char_width = module.char_width
            self._char_height = module.char_height
            self._atlas_width = module.atlas_width
            self._atlas_height = module.atlas_height
            self._first_char = module.first_char
            self._last_char = module.last_char
            self._chars_per_row = module.chars_per_row

            return True
        except ImportError as e:
            log.error("Failed to import font atlas: %s", e)
            return False

    def _create_font_texture(self):
        """Create the font texture from the atlas module."""
        if self._atlas_module is None:
            return False

        try:
            # Get PNG data from the atlas module
            png_data = self._atlas_module.get_png_data()

            # Load the PNG using PIL
            from PIL import Image
            img = Image.open(io.BytesIO(png_data))
            img = img.convert('RGBA')

            # Convert to numpy array (no flip)
            # PIL row 0 (top of image) = atlas row 0 (space, !, etc.)
            # When uploaded: array row 0 → texture V=0
            # So texture V=0 has atlas row 0
            texture_data = np.array(img, dtype=np.uint8)

            # Create OpenGL texture
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

            return True
        except Exception as e:
            log.error("Failed to create font texture: %s", e)
            return False

    def initialize(self):
        """Initialize the text renderer (must be called from GL context)."""
        if self._initialized:
            return True

        try:
            # Load atlas module
            if not self._load_atlas_module():
                return False

            # Create texture
            if not self._create_font_texture():
                return False

            # Create VAO and VBO for quad rendering
            self._vao = glGenVertexArrays(1)
            self._vbo = glGenBuffers(1)

            self._initialized = True
            return True
        except Exception as e:
            log.error("Failed to initialize shader text renderer: %s", e)
            return False

    @property
    def char_width(self):
        """Width of a single character in pixels."""
        return self._char_width

    @property
    def char_height(self):
        """Height of a single character in pixels."""
        return self._char_height

    @property
    def font_size(self):
        """Actual font size being used."""
        return self._actual_size

    @property
    def texture(self):
        """The atlas texture id, or None before initialize() has run.

        Exposed so another renderer -- the overlay UI, which batches text and
        widget frames into one draw with its own program -- can bind the same
        atlas rather than building a second copy of it.
        """
        return self._texture

    def glyph_uv(self, char):
        """Texture coordinates for one character, as (u0, v0, u1, v1).

        v0 goes with the *bottom* of the quad and v1 with the top: within a
        cell, low V is the top of the glyph, so the pair is swapped here and
        the caller draws the quad in ordinary screen order.  A character
        outside the atlas falls back to '?'.
        """
        code = ord(char)
        if code < self._first_char or code > self._last_char:
            code = ord('?')
        index = code - self._first_char
        col = index % self._chars_per_row
        row = index // self._chars_per_row
        return (col * self._char_width / self._atlas_width,
                (row + 1) * self._char_height / self._atlas_height,
                (col + 1) * self._char_width / self._atlas_width,
                row * self._char_height / self._atlas_height)

    def measure_text(self, text):
        """Measure the dimensions of rendered text.

        Args:
            text: String to measure

        Returns:
            Tuple of (width, height) in pixels
        """
        if not text:
            return (0, 0)

        lines = text.split('\n')
        max_width = max(len(line) for line in lines)
        num_lines = len(lines)

        return (max_width * self._char_width, num_lines * self._char_height)

    def render_text(self, text, x, y, shader_program, viewport_width, viewport_height,
                    color=(1.0, 1.0, 1.0, 1.0), background_color=None, scale=1.0):
        """Render text at screen position (x, y).

        Args:
            text: String to render
            x, y: Screen position (pixels from bottom-left)
            shader_program: ShaderProgram instance to use
            viewport_width, viewport_height: Viewport dimensions
            color: RGBA color tuple for text (foreground)
            background_color: RGBA color tuple for background, or None for transparent
            scale: Text scale factor (1.0 = native size)

        Examples:
            # White text on transparent background (default)
            renderer.render_text("Hello", 10, 10, shader, w, h)

            # Green text on transparent background
            renderer.render_text("Hello", 10, 10, shader, w, h,
                               color=(0.0, 1.0, 0.0, 1.0))

            # Black text on white solid background
            renderer.render_text("Hello", 10, 10, shader, w, h,
                               color=(0.0, 0.0, 0.0, 1.0),
                               background_color=(1.0, 1.0, 1.0, 1.0))
        """
        if not self._initialized:
            if not self.initialize():
                return

        if not text:
            return

        # Build vertex data for all characters
        vertices = []

        char_w = self._char_width * scale
        char_h = self._char_height * scale

        cursor_x = x
        cursor_y = y

        for char in text:
            if char == '\n':
                cursor_x = x
                cursor_y -= char_h * 1.2
                continue

            char_code = ord(char)
            if char_code < self._first_char or char_code > self._last_char:
                char_code = ord('?')  # Unknown character fallback

            char_idx = char_code - self._first_char
            col = char_idx % self._chars_per_row
            row = char_idx // self._chars_per_row

            # Texture coordinates
            # Without flip: PIL row 0 (atlas row 0) → texture V=0
            # Within a cell, low V = top of character glyph, high V = bottom of glyph
            # We want: screen y0 (bottom of quad) ← texture top of glyph (low V)
            #          screen y1 (top of quad) ← texture bottom of glyph (high V)
            # So we swap: v0 (used with y0) = high V, v1 (used with y1) = low V
            u0 = col * self._char_width / self._atlas_width
            u1 = (col + 1) * self._char_width / self._atlas_width
            # Character cell spans from row*char_height to (row+1)*char_height in image Y
            # In texture V: low image Y = low V
            v_top = row * self._char_height / self._atlas_height  # top of cell (glyph top)
            v_bottom = (row + 1) * self._char_height / self._atlas_height  # bottom of cell (glyph bottom)
            # Swap to render right-side up: bottom of quad gets top of glyph
            v0 = v_bottom  # used with y0 (bottom of quad)
            v1 = v_top     # used with y1 (top of quad)

            # Convert screen coordinates to NDC
            x0 = 2.0 * cursor_x / viewport_width - 1.0
            y0 = 2.0 * cursor_y / viewport_height - 1.0
            x1 = 2.0 * (cursor_x + char_w) / viewport_width - 1.0
            y1 = 2.0 * (cursor_y + char_h) / viewport_height - 1.0

            # Two triangles per character (6 vertices)
            # Position (x,y,z), TexCoord (u,v)
            vertices.extend([
                x0, y0, 0.0, u0, v0,
                x1, y0, 0.0, u1, v0,
                x1, y1, 0.0, u1, v1,

                x0, y0, 0.0, u0, v0,
                x1, y1, 0.0, u1, v1,
                x0, y1, 0.0, u0, v1,
            ])

            cursor_x += char_w

        if not vertices:
            return

        vertex_data = array(vertices, 'f')

        # Bind VAO and upload vertex data
        glBindVertexArray(self._vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, vertex_data.nbytes, vertex_data, GL_DYNAMIC_DRAW)

        # Use unlit shader for text
        shader_program.use(lit=False)

        # Set up orthographic projection (identity for NDC coordinates)
        identity = array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], 'f')
        shader_program.set_matrices(identity, identity, program=shader_program.unlit_program)

        # Enable texture and set texture uniform
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._texture)

        # Set the texture sampler uniform to texture unit 0
        tex_uniform_loc = glGetUniformLocation(shader_program.unlit_program, 'diffuseTexture')
        if tex_uniform_loc >= 0:
            glUniform1i(tex_uniform_loc, 0)

        # Determine if we're using solid background or transparent
        solid_bg = background_color is not None
        if not solid_bg:
            background_color = (0.0, 0.0, 0.0, 0.0)  # Default transparent

        # Set text rendering mode with colors
        shader_program.set_text_mode(
            enabled=True,
            text_color=color,
            background_color=background_color,
            solid_background=solid_bg
        )

        # Set up vertex attributes
        pos_loc = glGetAttribLocation(shader_program.unlit_program, 'aPosition')
        tex_loc = glGetAttribLocation(shader_program.unlit_program, 'aTexCoord')

        stride = 5 * 4  # 5 floats per vertex, 4 bytes per float

        if pos_loc >= 0:
            glEnableVertexAttribArray(pos_loc)
            glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, stride, None)

        if tex_loc >= 0:
            glEnableVertexAttribArray(tex_loc)
            glVertexAttribPointer(tex_loc, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        # Set up blending based on mode
        if solid_bg:
            # Solid background - no blending needed, just overwrite
            glDisable(GL_BLEND)
        else:
            # Transparent background - need alpha blending
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glDisable(GL_DEPTH_TEST)

        # Draw all character quads
        num_vertices = len(vertices) // 5
        glDrawArrays(GL_TRIANGLES, 0, num_vertices)

        # Cleanup
        if pos_loc >= 0:
            glDisableVertexAttribArray(pos_loc)
        if tex_loc >= 0:
            glDisableVertexAttribArray(tex_loc)

        # Disable text mode
        shader_program.set_text_mode(enabled=False)

        glBindTexture(GL_TEXTURE_2D, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        glEnable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)

        # Restore lit shader
        shader_program.use(lit=True)


# Cached text renderers, keyed by (GL context, size).  Per context and not
# merely per size: a renderer owns a texture, a VAO and a VBO, and those names
# mean nothing in another context, so a second window handed the first
# window's renderer draws the wrong thing or raises.
_renderers = {}


def _gl_context():
    """An identifier for the GL context that is current, or None."""
    try:
        from OpenGL import contextdata
        return contextdata.getContext()
    except Exception:                   # pragma: no cover - no GL at all
        return None


def get_text_renderer(font_size=16):
    """Get a text renderer for the specified font size.

    One per (GL context, size), built on first use and kept: an atlas costs a
    texture upload, and nine sizes must not become nine uploads a frame.

    Args:
        font_size: Desired font size in pixels

    Returns:
        ShaderTextRenderer instance
    """
    key = (_gl_context(), font_size)
    if key not in _renderers:
        _renderers[key] = ShaderTextRenderer(font_size)
    return _renderers[key]


def drop_text_renderers():
    """Forget the renderers belonging to the current GL context.

    Called as a window goes away.  Their GL objects die with the context, and a
    later context can be handed the same identifier by the driver, which would
    otherwise leave the new window drawing through names that are gone.
    """
    context = _gl_context()
    for key in [key for key in _renderers if key[0] == context]:
        del _renderers[key]
