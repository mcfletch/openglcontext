"""The reflection atlas and the GPU timer, against a real context."""
import numpy as np
import pytest
from OpenGL import GL as gl

from OpenGLContext.passes.gputimer import GpuTimer
from OpenGLContext.passes.reflectionatlas import LEVELS, ReflectionAtlas, atlas_size
from OpenGLContext.passes.reflectiontiles import GUTTER


@pytest.fixture
def gl_context(gl_window):
    return gl_window('reflection-atlas', size=(64, 64))


def test_the_atlas_is_a_share_of_the_windows_pixels():
    assert atlas_size(1920, 1080, 0.5) == (1360, 768)
    assert atlas_size(100, 100, 1.0) == (112, 112)


@pytest.mark.usefixtures('gl_context')
def test_a_cleared_tile_holds_nothing_and_its_neighbour_is_untouched():
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


@pytest.mark.usefixtures('gl_context')
def test_the_timer_measures_without_waiting():
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


@pytest.mark.usefixtures('gl_context')
def test_ending_a_timer_that_never_began_does_nothing():
    timer = GpuTimer()
    timer.end()
    assert timer.milliseconds is None


@pytest.mark.usefixtures('gl_context')
def test_each_reading_is_numbered_and_carries_what_its_frame_was_tagged():
    """The newest reading stays until another arrives; its number says when
    one has, and its tag is what the measured frame was drawn with."""
    timer = GpuTimer()
    try:
        assert timer.reading == 0 and timer.tag is None
        seen = []
        for frame in range(8):
            timer.begin(tag=frame)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            timer.end()
            gl.glFinish()
            seen.append((timer.reading, timer.tag))
        numbers = [number for number, _tag in seen]
        assert numbers == sorted(numbers) and numbers[-1] > 0
        for number, tag in seen:
            if number:
                assert tag is not None and tag < 8
        frames_later = [frame - tag for frame, (number, tag) in enumerate(seen) if number]
        assert all(later >= 1 for later in frames_later)
    finally:
        timer.release()


def _texels(texture, width, height):
    gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
    found = np.frombuffer(gl.glGetTexImage(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, gl.GL_FLOAT),
                          np.float32).reshape(height, width, 4)
    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
    return found


def _fill(atlas, colour):
    previous = atlas.begin()
    gl.glScissor(0, 0, *atlas.size)
    gl.glClearColor(*colour)
    gl.glClear(gl.GL_COLOR_BUFFER_BIT)
    atlas.end(previous)


@pytest.mark.usefixtures('gl_context')
def test_clearing_a_tile_clears_its_gutter_and_nothing_past_it():
    """The blurred levels a rough mirror reads reach into the gutter."""
    atlas = ReflectionAtlas()
    try:
        atlas.ensure_size(64, 32)
        _fill(atlas, (1.0, 0.5, 0.25, 1.0))
        previous = atlas.begin()
        atlas.clear((16, 8, 16, 16))
        atlas.end(previous)
        found = _texels(atlas.texture, 64, 32)
        assert found[8 + 8, 16 - GUTTER, 3] == 0.0          # the gutter, left
        assert found[8 + 16 + GUTTER - 1, 20, 3] == 0.0     # the gutter, above
        assert found[16, 16 - GUTTER - 1, 3] == 1.0          # past it
        assert found[8 + 16 + GUTTER, 20, 3] == 1.0
    finally:
        atlas.release()


@pytest.mark.usefixtures('gl_context')
def test_a_gutter_at_the_edge_of_the_atlas_is_clipped_to_it():
    atlas = ReflectionAtlas()
    try:
        atlas.ensure_size(32, 32)
        _fill(atlas, (1.0, 1.0, 1.0, 1.0))
        previous = atlas.begin()
        atlas.clear((0, 0, 8, 8))
        atlas.end(previous)
        found = _texels(atlas.texture, 32, 32)
        assert found[0, 0, 3] == 0.0 and found[31, 31, 3] == 1.0
    finally:
        atlas.release()


@pytest.mark.usefixtures('gl_context')
def test_keeping_copies_only_the_tiles_named():
    atlas = ReflectionAtlas()
    try:
        atlas.ensure_size(64, 32)
        _fill(atlas, (1.0, 0.0, 0.0, 1.0))
        atlas.keep([(0, 0, 64, 32)])
        _fill(atlas, (0.0, 1.0, 0.0, 1.0))
        atlas.keep([(8, 8, 8, 8)])
        kept = _texels(atlas.kept, 64, 32)
        assert tuple(kept[10, 10]) == pytest.approx((0.0, 1.0, 0.0, 1.0))
        assert tuple(kept[30, 60]) == pytest.approx((1.0, 0.0, 0.0, 1.0))
    finally:
        atlas.release()


@pytest.mark.usefixtures('gl_context')
def test_the_atlas_leaves_the_state_it_found():
    """Clear colour, the texture on the active unit and both framebuffer
    bindings are as they were after every call."""
    texture = int(gl.glGenTextures(1))
    read, draw = (int(name) for name in gl.glGenFramebuffers(2))
    atlas = ReflectionAtlas()
    try:
        for name in (read, draw):
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, name)
            colour = int(gl.glGenRenderbuffers(1))
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, colour)
            gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_RGBA8, 8, 8)
            gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                         gl.GL_RENDERBUFFER, colour)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, draw)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glClearColor(0.25, 0.5, 0.75, 1.0)

        def state():
            return (tuple(float(v) for v in gl.glGetFloatv(gl.GL_COLOR_CLEAR_VALUE)),
                    int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),
                    int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)),
                    int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D)))

        before = state()
        atlas.ensure_size(32, 32)
        assert state() == before
        atlas.keep([(0, 0, 32, 32)])
        assert state() == before
        previous = atlas.begin()
        atlas.clear((0, 0, 8, 8))
        atlas.end(previous, mipmap=True)
        assert state() == before
    finally:
        atlas.release()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glDeleteFramebuffers(2, [read, draw])
        gl.glDeleteTextures([texture])
