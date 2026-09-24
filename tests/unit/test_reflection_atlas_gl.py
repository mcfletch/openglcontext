"""The reflection atlas and the GPU timer, against a real context."""
import numpy as np
import pytest

from OpenGLContext.passes.gputimer import GpuTimer
from OpenGLContext.passes.reflectionatlas import LEVELS, ReflectionAtlas, atlas_size


@pytest.fixture
def gl_context(gl_window):
    return gl_window('reflection-atlas', size=(64, 64))


def test_the_atlas_is_a_share_of_the_windows_pixels():
    assert atlas_size(1920, 1080, 0.5) == (1360, 768)
    assert atlas_size(100, 100, 1.0) == (112, 112)


def test_a_cleared_tile_holds_nothing_and_its_neighbour_is_untouched(gl_context):
    from OpenGL import GL as gl
    atlas = ReflectionAtlas()
    try:
        assert atlas.ensure_size(64, 32)
        assert not atlas.ensure_size(64, 32)
        previous = atlas.begin()
        atlas.clear((0, 0, 64, 32))
        gl.glScissor(0, 0, 64, 32)
        gl.glClearColor(1.0, 0.5, 0.25, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        atlas.clear((8, 8, 16, 16))
        atlas.end(previous, mipmap=True)
        assert atlas.mipmapped
        gl.glBindTexture(gl.GL_TEXTURE_2D, atlas.texture)
        texels = np.frombuffer(gl.glGetTexImage(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA,
                                                gl.GL_FLOAT), np.float32).reshape(32, 64, 4)
        assert texels[12, 12, 3] == 0.0
        assert tuple(texels[2, 40]) == pytest.approx((1.0, 0.5, 0.25, 1.0))
        levels = int(gl.glGetTexParameteriv(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_IMMUTABLE_LEVELS))
        assert levels == LEVELS
    finally:
        atlas.release()
    assert atlas.size == (0, 0) and not atlas.texture


def test_the_timer_measures_without_waiting(gl_context):
    from OpenGL import GL as gl
    timer = GpuTimer()
    try:
        for _ in range(12):
            timer.begin()
            gl.glClearColor(0.1, 0.2, 0.3, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            timer.end()
            gl.glFinish()
        assert timer.milliseconds is not None
        assert 0.0 <= timer.milliseconds < 1000.0
    finally:
        timer.release()


def test_ending_a_timer_that_never_began_does_nothing(gl_context):
    timer = GpuTimer()
    timer.end()
    assert timer.milliseconds is None
