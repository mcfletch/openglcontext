"""The depth and stencil buffer dumps in `OpenGLContext.debug.bufferimage`."""
import pytest

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_SCISSOR_TEST,
    GL_STENCIL_BUFFER_BIT,
    glClear, glClearColor, glClearDepth, glClearStencil, glDisable, glEnable,
    glScissor,
)

from OpenGLContext.debug import bufferimage

WIDTH, HEIGHT = 16, 12


@pytest.fixture
def gl_context(gl_window):
    return gl_window('bufferimage', size=(WIDTH, HEIGHT),
                     hints={'STENCIL_BITS': 8})


def _clear(depth: float = 1.0, stencil: int = 0) -> None:
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClearDepth(depth)
    glClearStencil(stencil)
    glEnable(GL_DEPTH_TEST)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)


def _clear_rect(x: int, y: int, width: int, height: int,
                depth: float = 0.0, stencil: int = 0) -> None:
    """Clear one rectangle of the buffers, leaving the rest as it was."""
    glEnable(GL_SCISSOR_TEST)
    glScissor(x, y, width, height)
    glClearDepth(depth)
    glClearStencil(stencil)
    glClear(GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
    glDisable(GL_SCISSOR_TEST)


def test_depth_normalises_a_uniform_buffer(gl_context):
    """A depth dump of a cleared buffer is an image, not an exception."""
    _clear(depth=1.0)
    image = bufferimage.depth(0, 0, WIDTH, HEIGHT)
    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == 'L'


def test_depth_values_stay_inside_a_byte(gl_context):
    """The far plane is white: the depth range is scaled across the byte."""
    _clear(depth=1.0)
    image = bufferimage.depth(0, 0, WIDTH, HEIGHT, normalise=False)
    assert image.getextrema() == (255, 255)


def test_depth_normalisation_spans_the_byte(gl_context):
    """Normalising puts the nearest depth at black and the furthest at white."""
    _clear(depth=1.0)
    _clear_rect(0, 0, WIDTH, HEIGHT // 2, depth=0.5)
    image = bufferimage.depth(0, 0, WIDTH, HEIGHT)
    assert image.getextrema() == (0, 255)


def test_depth_reads_the_rectangle_it_is_asked_for(gl_context):
    """The x,y origin is honoured rather than being read from the corner."""
    _clear(depth=1.0)
    _clear_rect(8, 4, 4, 4, depth=0.0)
    near = bufferimage.depth(8, 4, 4, 4, normalise=False)
    far = bufferimage.depth(0, 0, 4, 4, normalise=False)
    assert near.getextrema() == (0, 0)
    assert far.getextrema() == (255, 255)


def test_stencil_reads_the_rectangle_it_is_asked_for(gl_context):
    """The stencil dump honours x,y as well."""
    _clear(stencil=3)
    _clear_rect(8, 4, 4, 4, stencil=7)
    assert bufferimage.stencil(8, 4, 4, 4).getextrema() == (7, 7)
    assert bufferimage.stencil(0, 0, 4, 4).getextrema() == (3, 3)


def test_the_default_rectangle_is_the_whole_viewport(gl_context):
    """No rectangle given means the viewport."""
    _clear()
    assert bufferimage.depth().size == (WIDTH, HEIGHT)
    assert bufferimage.stencil().size == (WIDTH, HEIGHT)


def test_flip_puts_the_first_gl_row_at_the_bottom(gl_context):
    """GL numbers rows from the bottom, PIL from the top; ``flip`` reconciles.

    The dump is not mirrored left to right either way, so a patch on the right
    of the buffer stays on the right of the image.
    """
    _clear(depth=1.0, stencil=0)
    _clear_rect(8, 0, 8, 4, depth=0.0, stencil=9)
    flipped = bufferimage.stencil(0, 0, WIDTH, HEIGHT)
    unflipped = bufferimage.stencil(0, 0, WIDTH, HEIGHT, flip=False)
    assert flipped.getpixel((12, HEIGHT - 1)) == 9
    assert flipped.getpixel((12, 0)) == 0
    assert unflipped.getpixel((12, 0)) == 9
    assert unflipped.getpixel((12, HEIGHT - 1)) == 0
    # Not mirrored: the left half is untouched in both.
    assert flipped.getpixel((2, HEIGHT - 1)) == 0
    assert unflipped.getpixel((2, 0)) == 0
