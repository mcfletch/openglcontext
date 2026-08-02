"""A picture is drawn the way up it was authored.

Against a real framebuffer, because this is exactly the kind of thing that is
invisible in arithmetic and obvious on screen: the answer is which pixels ended
up where, so the test reads them.

PIL hands over its rows **top first** and a GL texture's ``v`` runs **bottom
up**, so uploading the bytes as they come and drawing them with the obvious
texture coordinates puts the picture on its head.  Nothing catches that until
somebody looks at a photograph.
"""

import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")
Image = pytest.importorskip("PIL.Image")

WIDTH = HEIGHT = 64

#: Distinct enough that no blend or rounding can confuse the two halves.
TOP_COLOUR = (255, 0, 0)
BOTTOM_COLOUR = (0, 0, 255)


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    window = glfw.create_window(WIDTH, HEIGHT, "picture", None, None)
    if not window:
        pytest.skip("no GL window")
    glfw.make_context_current(window)
    yield window
    from OpenGLContext.scenegraph.text import shadertext
    shadertext.drop_text_renderers()
    glfw.destroy_window(window)


@pytest.fixture
def renderer(gl_context):
    from OpenGL.GL import glViewport
    from OpenGLContext.ui.draw import OverlayRenderer
    glViewport(0, 0, WIDTH, HEIGHT)
    made = OverlayRenderer(16)
    if not made.initialize():
        pytest.skip("no font atlas / program on this driver")
    yield made
    made.close()


@pytest.fixture
def two_tone(tmp_path):
    """A PNG whose top half is red and whose bottom half is blue."""
    pixels = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    pixels[:HEIGHT // 2] = TOP_COLOUR            # PIL row 0 is the top
    pixels[HEIGHT // 2:] = BOTTOM_COLOUR
    path = tmp_path / 'two_tone.png'
    Image.fromarray(pixels, 'RGB').save(path)
    return str(path)


def _drawn(renderer, url):
    """Draw the picture over the whole viewport and read the frame back.

    Returns ``(top_row, bottom_row)`` as RGB triples, where *top* means the top
    of the window as a person sees it.
    """
    from OpenGL.GL import (
        glClear, glClearColor, glReadPixels, GL_COLOR_BUFFER_BIT, GL_RGB,
        GL_UNSIGNED_BYTE,
    )
    from OpenGLContext.ui.geometry import Rect
    found = renderer.imageTexture(url)
    assert found is not None, 'the picture would not load at all'
    texture, _width, _height = found
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    renderer.begin((WIDTH, HEIGHT))
    renderer.quad(Rect(0, 0, WIDTH, HEIGHT), (1, 1, 1, 1), texture=texture)
    renderer.end()
    raw = glReadPixels(0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE)
    # glReadPixels hands back the bottom row first.
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
    return tuple(int(v) for v in frame[-1][WIDTH // 2]), \
        tuple(int(v) for v in frame[0][WIDTH // 2])


def test_the_top_of_the_picture_is_at_the_top_of_the_screen(renderer, two_tone):
    top, _bottom = _drawn(renderer, two_tone)
    assert top == TOP_COLOUR, 'the picture is upside down'


def test_the_bottom_of_the_picture_is_at_the_bottom(renderer, two_tone):
    _top, bottom = _drawn(renderer, two_tone)
    assert bottom == BOTTOM_COLOUR, 'the picture is upside down'
