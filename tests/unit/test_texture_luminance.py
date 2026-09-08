"""A greyscale image is grey when it is sampled, not red.

A luminance texture means one channel standing for all three: sampling it gives
``(L, L, L, 1)``. That is what a light map is for, and what a greyscale mask, a
single-channel glyph sheet or a height field read as a texture all rely on.

``GL_LUMINANCE`` carried the meaning and is not a format a core profile will
accept, so the upload uses ``GL_R8``, which samples as ``(R, 0, 0, 1)``: green
and blue dropped on the floor. A light map modulating a wall then annihilates
two of its channels and leaves it dark red, which is what
``tests/nehe6_multi.py`` and ``tests/multitexture_1.py`` were drawing.

The measurement has to be a sample, not a read of the stored texels:
``glGetTexImage`` returns what was uploaded and does not apply the swizzle, so
it reports the failure and the fix identically. These tests put the texture
through the fixed-function texture unit -- the pipeline both those demos draw
with -- and read the pixel that comes out.
"""

import numpy as np
import pytest

pytest.importorskip("glfw")
PIL = pytest.importorskip("PIL.Image")

from OpenGL.GL import (  # noqa: E402
    GL_ALPHA, GL_BLEND, GL_BLUE, GL_COLOR_BUFFER_BIT, GL_DEPTH_TEST, GL_GREEN,
    GL_LIGHTING, GL_MODELVIEW, GL_MODULATE, GL_ONE, GL_ONE_MINUS_SRC_ALPHA,
    GL_PROJECTION, GL_QUADS, GL_RED, GL_REPLACE, GL_RGBA, GL_SRC_ALPHA,
    GL_TEXTURE_2D, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_TEXTURE_SWIZZLE_A,
    GL_TEXTURE_SWIZZLE_B, GL_TEXTURE_SWIZZLE_G, GL_TEXTURE_SWIZZLE_R,
    GL_UNSIGNED_BYTE, glBegin, glBlendFunc, glClear, glClearColor, glColor4f,
    glDisable, glEnable, glEnd, glFinish, glGetTexParameteriv, glLoadIdentity,
    glMatrixMode, glOrtho, glReadPixels, glTexCoord2f, glTexEnvi, glVertex3f,
    glViewport,
)

from OpenGLContext import texture as texture_module  # noqa: E402

LUMINANCE = 128
ALPHA = 64


def _image(mode):
    """A flat image of a known value, so the pixel that comes back is predictable."""
    if mode == 'L':
        return PIL.fromarray(np.full((4, 4), LUMINANCE, dtype='B'), 'L')
    if mode == 'LA':
        return PIL.fromarray(np.dstack([
            np.full((4, 4), LUMINANCE, dtype='B'),
            np.full((4, 4), ALPHA, dtype='B')]), 'LA')
    return PIL.fromarray(np.dstack([
        np.full((4, 4), 200, dtype='B'),
        np.full((4, 4), 100, dtype='B'),
        np.full((4, 4), 50, dtype='B')]), 'RGB')


def _sampled(mode, env_mode=GL_REPLACE, blend_over=None):
    """The pixel a textured quad draws, as 0..255 RGBA.

    ``GL_REPLACE`` puts the texel on the screen untouched, so what comes back is
    what the texture unit fetched. ``blend_over`` clears to that colour first and
    blends the quad onto it by its alpha, which is how the alpha channel is read.
    """
    texture = texture_module.Texture(_image(mode))

    glViewport(0, 0, 32, 32)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(0, 1, 0, 1, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    glDisable(GL_LIGHTING)
    glDisable(GL_DEPTH_TEST)
    glClearColor(*((blend_over + (1.0,)) if blend_over else (0.0, 0.0, 0.0, 1.0)))
    glClear(GL_COLOR_BUFFER_BIT)
    if blend_over:
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    else:
        glDisable(GL_BLEND)

    texture()                       # bind + enable the fixed-function unit
    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, env_mode)
    glColor4f(1.0, 1.0, 1.0, 1.0)
    glBegin(GL_QUADS)
    for (s, t) in ((0, 0), (1, 0), (1, 1), (0, 1)):
        glTexCoord2f(s, t)
        glVertex3f(s, t, 0)      # the quad is the unit square, so uv is xy
    glEnd()
    glDisable(GL_TEXTURE_2D)
    glFinish()

    pixels = glReadPixels(16, 16, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
    return np.frombuffer(pixels, dtype='B').astype(int)


def test_a_greyscale_texture_draws_grey(gl_context_compat):
    """Red, green and blue all carry the one channel that was uploaded."""
    red, green, blue, _ = _sampled('L')
    assert (red, green, blue) == pytest.approx((LUMINANCE, LUMINANCE, LUMINANCE), abs=2)


def test_a_greyscale_texture_modulates_every_channel(gl_context_compat):
    """The light-map case: it dims a surface rather than colouring it.

    Under ``GL_MODULATE`` a texel of (L, 0, 0, 1) multiplies green and blue by
    zero, which is the whole of the defect -- a wall lit by a grey light map
    came out red.
    """
    red, green, blue, _ = _sampled('L', GL_MODULATE)
    assert green > 0 and blue > 0, "the light map annihilated green and blue"
    assert (red, green, blue) == pytest.approx((LUMINANCE, LUMINANCE, LUMINANCE), abs=2)


def test_a_greyscale_texture_is_fully_opaque(gl_context_compat):
    """Nothing was uploaded into alpha, so it samples as 1 rather than as the red."""
    assert _sampled('L')[3] == pytest.approx(255, abs=2)


@pytest.mark.parametrize('mode,expected', [
    ('L', (GL_RED, GL_RED, GL_RED, GL_ONE)),
    ('LA', (GL_RED, GL_RED, GL_RED, GL_GREEN)),
    ('RGB', (GL_RED, GL_GREEN, GL_BLUE, GL_ALPHA)),
])
def test_the_texture_is_told_which_channel_stands_for_which(gl_context_compat, mode, expected):
    """The swizzle each format is uploaded with, read back off the texture.

    The single-channel case is asserted through a drawn pixel above; this is how
    the two-channel one is asserted, because the fixed-function texture
    environment is defined for the base formats the old enums named and a
    two-channel ``GL_RG8`` is not among them -- what a driver does with one there
    is its own business. A shader samples the swizzle directly and gets
    ``(L, L, L, A)``, and the colour case is here to say the replication is not
    applied to formats that carry their own channels.
    """
    texture_module.Texture(_image(mode)).bind()
    parameters = (GL_TEXTURE_SWIZZLE_R, GL_TEXTURE_SWIZZLE_G,
                  GL_TEXTURE_SWIZZLE_B, GL_TEXTURE_SWIZZLE_A)
    actual = tuple(int(glGetTexParameteriv(GL_TEXTURE_2D, p)) for p in parameters)
    assert actual == tuple(int(e) for e in expected)


def test_a_colour_texture_is_left_alone(gl_context_compat):
    """The replication is for the single-channel formats and nothing else."""
    red, green, blue, alpha = _sampled('RGB')
    assert (red, green, blue) == pytest.approx((200, 100, 50), abs=2)
    assert alpha == pytest.approx(255, abs=2)
