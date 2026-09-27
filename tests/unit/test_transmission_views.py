"""Glass in a window of several views, and the backdrop it refracts.

A transmissive surface samples a copy of the opaque scene behind it, addressed
by where it falls in its own view. With several views on one window that copy
has to be of the view being drawn: a copy of the whole window puts every other
view -- the whole grid of them, shrunk -- inside the glass.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_RGB, GL_SCISSOR_TEST, GL_TEXTURE_2D, GL_UNSIGNED_BYTE,
    glBindTexture, glClear, glClearColor, glDisable, glEnable, glGetTexImage,
    glScissor, glViewport,
)

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle
from OpenGLContext.passes import renderpass
from OpenGLContext.passes.transmission import TransmissionBackdrops, TransmissionBuffer
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.testing.stillframe import check_still_frame
from tests.unit.glrender import base_env, frames_of

WIDTH, HEIGHT = 200, 100
RED = (1.0, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)


def _clear_rect(rect, colour):
    glScissor(*rect)
    glEnable(GL_SCISSOR_TEST)
    glClearColor(*colour, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glDisable(GL_SCISSOR_TEST)


def _texture_pixels(buffer):
    glBindTexture(GL_TEXTURE_2D, buffer.tex)
    try:
        data = glGetTexImage(GL_TEXTURE_2D, 0, GL_RGB, GL_UNSIGNED_BYTE)
    finally:
        glBindTexture(GL_TEXTURE_2D, 0)
    return np.frombuffer(data, np.uint8).reshape(buffer.h, buffer.w, 3)


@pytest.mark.usefixtures('gl_context')
def test_capture_copies_the_rectangle_at_its_origin():
    """A backdrop sized to one view holds that view, not the window's corner."""
    glViewport(0, 0, 64, 64)
    _clear_rect((0, 0, 32, 64), RED)
    _clear_rect((32, 0, 32, 64), GREEN)
    buffer = TransmissionBuffer()
    try:
        buffer.ensure_size(32, 64)
        buffer.capture(32, 0)
        pixels = _texture_pixels(buffer).astype(int)
        assert pixels[..., 1].min() > 200, 'the right-hand half was not copied'
        assert pixels[..., 0].max() < 50, 'the left-hand half was copied'
    finally:
        buffer.release()


@pytest.mark.usefixtures('gl_context')
def test_capture_defaults_to_the_framebuffer_origin():
    """With no origin the copy starts at the lower-left corner, as for one view."""
    glViewport(0, 0, 64, 64)
    _clear_rect((0, 0, 32, 64), RED)
    _clear_rect((32, 0, 32, 64), GREEN)
    buffer = TransmissionBuffer()
    try:
        buffer.ensure_size(32, 64)
        buffer.capture()
        pixels = _texture_pixels(buffer).astype(int)
        assert pixels[..., 0].min() > 200
        assert pixels[..., 1].max() < 50
    finally:
        buffer.release()


class TestBackdrops:
    @pytest.mark.usefixtures('gl_context')
    def test_each_size_of_view_has_its_own_backdrop(self):
        backdrops = TransmissionBackdrops()
        sizes = [(60, 40), (140, 40)]
        try:
            narrow = backdrops.for_view(60, 40, sizes)
            wide = backdrops.for_view(140, 40, sizes)
            assert (narrow.w, narrow.h) == (60, 40)
            assert (wide.w, wide.h) == (140, 40)
            # The next frame finds both where it left them.
            assert backdrops.for_view(60, 40, sizes) is narrow
            assert backdrops.for_view(140, 40, sizes).tex == wide.tex
        finally:
            backdrops.release()
        assert backdrops.buffers == {}
        assert narrow.tex is None and wide.tex is None

    @pytest.mark.usefixtures('gl_context')
    def test_views_of_one_size_share_a_backdrop(self):
        backdrops = TransmissionBackdrops()
        sizes = [(50, 50)] * 4
        try:
            first = backdrops.for_view(50, 50, sizes)
            assert backdrops.for_view(50, 50, sizes) is first
            assert list(backdrops.buffers) == [(50, 50)]
        finally:
            backdrops.release()

    @pytest.mark.usefixtures('gl_context')
    def test_a_size_the_layout_no_longer_has_is_released(self):
        """Moving a splitter leaves nothing behind for the sizes it moved away from."""
        backdrops = TransmissionBackdrops()
        try:
            old = backdrops.for_view(60, 40, [(60, 40), (140, 40)])
            backdrops.for_view(80, 40, [(80, 40), (120, 40)])
            assert old.tex is None
            assert set(backdrops.buffers) == {(80, 40)}
        finally:
            backdrops.release()

    @pytest.mark.usefixtures('gl_context')
    def test_the_view_drawn_is_kept_whatever_the_sizes_say(self):
        """A view missing from ``sizes`` still gets a backdrop, clamped to a pixel."""
        backdrops = TransmissionBackdrops()
        try:
            buffer = backdrops.for_view(0, 0)
            assert (buffer.w, buffer.h) == (1, 1)
            assert backdrops.for_view(0, 0) is buffer
        finally:
            backdrops.release()


def _glass_pane(x):
    """A clear pane filling most of a view that looks at it from six units."""
    material = PBRMaterial(baseColor=(1.0, 1.0, 1.0), transmission=1.0,
                           roughness=0.0, metallic=0.0, ior=1.0)
    return basenodes.Transform(translation=(x, 0, 0), children=[
        basenodes.Shape(geometry=basenodes.Box(size=(8.0, 8.0, 0.1)),
                        appearance=basenodes.Appearance(material=material))])


def _camera(x):
    return ViewPlatform(position=(x, 0, 6.0), orientation=(0, 1, 0, 0))


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999',
             OPENGLCONTEXT_BLOOM='0', OPENGLCONTEXT_TRANSMISSION='full')


@pytest.mark.usefixtures('env')
def test_glass_refracts_its_own_view(render_scene):
    """Glass in the second of two views shows that view's background, not the first view.

    The left view clears to red and is drawn first; the right one clears to
    green and looks through a pane of glass. Everything behind the glass is
    green, so every pixel of the right view is green.
    """
    def layout(_context):
        return ViewLayout.split(
            View(_camera(-40.0), name='red', style=ViewStyle(background=RED)),
            View(_camera(40.0), name='glass', style=ViewStyle(background=GREEN)))

    frames = frames_of(render_scene, [_glass_pane(40.0)], frames=3,
                       size=(WIDTH, HEIGHT), layout=layout)
    frame = frames[-1].astype(int)
    glass = frame[4:-4, WIDTH // 2 + 4:WIDTH - 4]
    assert frame[:, :WIDTH // 2 - 1, 0].min() > 200, 'the red view is not red'
    assert (glass[..., 1] > glass[..., 0] + 100).all(), (
        'the glass shows another view: red up to %d' % glass[..., 0].max())


@pytest.mark.usefixtures('env')
def test_glass_in_one_view_fills_the_window(render_scene):
    """A single view's glass still refracts the whole of the window behind it."""
    def layout(_context):
        return ViewLayout([View(_camera(40.0), name='glass',
                                style=ViewStyle(background=GREEN))])

    frames = frames_of(render_scene, [_glass_pane(40.0)], frames=3,
                       size=(WIDTH, HEIGHT), layout=layout)
    frame = frames[-1].astype(int)[4:-4, 4:-4]
    assert (frame[..., 1] > frame[..., 0] + 100).all()


def test_a_still_frame_of_glass_in_unequal_views_allocates_nothing(scene_context):
    """Views of two sizes each keep their backdrop from one frame to the next."""
    environment = {'OPENGLCONTEXT_RENDERER': 'pbr', 'OPENGLCONTEXT_TRANSMISSION': 'full'}
    with scene_context([_glass_pane(-40.0), _glass_pane(40.0)], size=(WIDTH, HEIGHT),
                       environment=environment) as context:
        context.viewLayout = ViewLayout.split(
            View(_camera(-40.0), name='narrow', style=ViewStyle(background=RED)),
            View(_camera(40.0), name='wide', style=ViewStyle(background=GREEN)),
            fraction=0.3)
        # Each view's glass captures the opaque scene behind it every frame,
        # and filling that backdrop's mip chain is one upload a view.
        work = check_still_frame(lambda: context.OnDraw(force=1), uploads=2)
        backdrops = renderpass.FLAT._transmission_backdrops  # noqa: SLF001 the pass's own backdrops, which this test is about
        assert sorted(backdrops.buffers) == [(60, HEIGHT), (140, HEIGHT)]
    assert work.allocations == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
