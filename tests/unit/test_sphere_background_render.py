"""In-process GL test: a gradient-sphere Background paints its stops.

:class:`OpenGLContext.scenegraph.background.Background` compounds its sky and
ground stops into one angle:colour set (``colorSet``), lays a sphere along it
(``buildSphere``) and draws that through the background shader
(``RenderShader``). Everything about the result follows from the stops: the top
of the frame is the colour at angle 0, the bottom the colour at pi, and what is
between them is the gradient.

``tests/unit/test_sphere_background_stops.py`` covers the stop arithmetic on its
own; this drives the whole path against a real context.
"""
import math

import numpy as np
import pytest

from vrml import cache

from OpenGLContext.scenegraph.background import Background


RED = (1.0, 0.0, 0.0)
BLUE = (0.0, 0.0, 1.0)
GREEN = (0.0, 1.0, 0.0)

SIZE = 96


@pytest.fixture
def gl_context(gl_window):
    """A context of this test's own, at a size the bands are readable at."""
    return gl_window('sphere-bg', size=(SIZE, SIZE))


def _perspective(fovy, aspect, near, far):
    """Row-vector perspective (clip = vertex_row . P), matching the engine."""
    f = 1.0 / math.tan(fovy / 2.0)
    P = np.zeros((4, 4), dtype='f')
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = -1.0
    P[3, 2] = (2 * far * near) / (near - far)
    return P


class _Mode:
    """What ``RenderShader`` reads of a rendering pass."""

    passCount = 0

    def __init__(self):
        self.cache = cache.Cache()
        self.matrix = np.identity(4, dtype='f')
        self.projection = _perspective(math.radians(60), 1.0, 0.5, 500.0)


def _frame(background, clear=True):
    """Draw the background alone and read the frame back, top row first."""
    from OpenGL.GL import (
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_FRAMEBUFFER, GL_RGB,
        GL_UNSIGNED_BYTE, glBindFramebuffer, glClear, glClearColor,
        glReadPixels, glViewport,
    )
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glViewport(0, 0, SIZE, SIZE)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    background.RenderShader(mode=_Mode(), clear=clear)
    raw = glReadPixels(0, 0, SIZE, SIZE, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3)[::-1]


def _band(image, top, bottom):
    return image[top:bottom].reshape(-1, 3).mean(0)


def _bound(**fields):
    background = Background(**fields)
    background.bound = 1
    return background


class TestAGradientSky:
    """Red overhead grading to blue at the horizon and below."""

    @pytest.fixture
    def image(self, gl_context):
        return _frame(_bound(
            skyColor=[RED, BLUE], skyAngle=[math.pi / 2.0],
            groundColor=[BLUE], groundAngle=[],
        )).astype(int)

    def test_something_is_drawn(self, image):
        assert image.max() > 20, image.reshape(-1, 3).mean(0).tolist()

    def test_the_first_stop_shows_at_the_top(self, image):
        """The camera looks at the horizon, so the top of the frame is part
        way up the gradient rather than the zenith: red is there, and it is
        not there at the bottom."""
        top = _band(image, 0, 12)
        bottom = _band(image, SIZE - 12, SIZE)
        assert top[0] > bottom[0] + 40, (top.tolist(), bottom.tolist())

    def test_the_bottom_is_the_last_stop(self, image):
        bottom = _band(image, SIZE - 12, SIZE)
        assert bottom[2] > bottom[0] + 40, bottom.tolist()

    def test_it_grades_between_them(self, image):
        """Red falls and blue rises from top to bottom, monotonically enough."""
        reds = [float(_band(image, y, y + 8)[0]) for y in range(0, SIZE, 8)]
        blues = [float(_band(image, y, y + 8)[2]) for y in range(0, SIZE, 8)]
        assert reds[0] > reds[-1] + 40, reds
        assert blues[-1] > blues[0] + 40, blues


class TestSkyAndGround:
    """A ground colour paints the lower half."""

    @pytest.fixture
    def image(self, gl_context):
        return _frame(_bound(
            skyColor=[BLUE], skyAngle=[],
            groundColor=[GREEN, GREEN], groundAngle=[math.pi / 2.0],
        )).astype(int)

    def test_the_ground_shows_below(self, image):
        bottom = _band(image, SIZE - 12, SIZE)
        assert bottom[1] > bottom[2] + 30, bottom.tolist()

    def test_the_sky_shows_above(self, image):
        top = _band(image, 0, 12)
        assert top[2] > top[1] + 30, top.tolist()


class TestOneColourAllOver:
    """A single sky colour with no angle spans the sphere."""

    def test_the_whole_frame_is_that_colour(self, gl_context):
        image = _frame(_bound(skyColor=[RED])).astype(int)
        for band in (_band(image, 0, 12), _band(image, SIZE - 12, SIZE)):
            assert band[0] > 120, band.tolist()
            assert band[1] < 60 and band[2] < 60, band.tolist()


class TestWhenThereIsNothingToDraw:
    def test_no_colours_leaves_the_frame_alone(self, gl_context):
        background = _bound(skyColor=[], skyAngle=[],
                            groundColor=[], groundAngle=[])
        assert _frame(background, clear=False).max() == 0

    def test_an_unbound_background_draws_nothing(self, gl_context):
        background = Background(skyColor=[RED])
        background.bound = 0
        assert _frame(background, clear=False).max() == 0

    def test_a_later_pass_draws_nothing(self, gl_context):
        """The background is the first thing in a frame or it is nothing."""
        background = _bound(skyColor=[RED])
        mode = _Mode()
        mode.passCount = 1
        assert not background.RenderShader(mode=mode, clear=False)


class TestTheCompiledSphereIsReused:
    """The vertex buffers are cached against the pass, keyed on the fields."""

    def test_a_second_draw_reuses_the_first(self, gl_context):
        background = _bound(skyColor=[RED, BLUE], skyAngle=[math.pi / 2.0])
        mode = _Mode()
        background.RenderShader(mode=mode, clear=False)
        first = mode.cache.getData(background, 'shader_bg')
        assert first is not None
        background.RenderShader(mode=mode, clear=False)
        assert mode.cache.getData(background, 'shader_bg') is first

    def test_changing_a_colour_rebuilds_it(self, gl_context):
        background = _bound(skyColor=[RED, BLUE], skyAngle=[math.pi / 2.0])
        mode = _Mode()
        background.RenderShader(mode=mode, clear=False)
        assert mode.cache.getData(background, 'shader_bg') is not None
        background.skyColor = [GREEN, BLUE]
        assert mode.cache.getData(background, 'shader_bg') is None
