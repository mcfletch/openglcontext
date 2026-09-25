"""In-process GL lifecycle tests for the two selection framebuffers.

:class:`SelectionFBO` (small per-pick region FBO) and
:class:`SelectionBufferFBO` (full-resolution MRT id buffer) are pure GL-resource
holders, so a hidden GLFW core-profile window is enough to exercise create /
resize / bind / clear / readback / blit / delete without any pass or scenegraph.
Skips cleanly when a GL context can't be created.
"""

import numpy as np
import pytest


from OpenGL.GL import (
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE, GL_NO_ERROR, GL_RGBA, GL_UNSIGNED_BYTE,
    glBindFramebuffer, glCheckFramebufferStatus, glClear, glClearColor, glDrawBuffers, glGetError,
    glReadPixels, glViewport,
)

from OpenGLContext.passes import selectionbuffers
from OpenGLContext.passes.selectionbuffers import SelectionFBO, SelectionBufferFBO


@pytest.fixture
def gl_context(gl_window):
    return gl_window('selbuf', size=(96, 96))


def _fill_id_texture(rgba):
    """Clear ONLY the id attachment (attachment 1) to an encoded RGBA colour."""
    glDrawBuffers(1, [GL_COLOR_ATTACHMENT1])
    glClearColor(*[c / 255.0 for c in rgba])
    glClear(GL_COLOR_BUFFER_BIT)


# --------------------------------------------------------------------------- #
# SelectionFBO
# --------------------------------------------------------------------------- #
class TestSelectionFBO:
    def test_initial_state_before_gpu_resources(self):
        fbo = SelectionFBO(max_width=64, max_height=64)
        assert fbo.fbo is None
        assert fbo.color_texture is None
        assert fbo.depth_renderbuffer is None
        assert fbo._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_bind_rejects_zero_region(self):
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 0, 0) is False
        assert fbo._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_bind_creates_complete_fbo(self):
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is True
        assert fbo.fbo is not None
        assert fbo.color_texture is not None
        assert fbo.depth_renderbuffer is not None
        assert glCheckFramebufferComplete() is True
        fbo.unbind()

    @pytest.mark.usefixtures('gl_context')
    def test_read_pixel_roundtrips_cleared_colour(self):
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is True
        glViewport(0, 0, 8, 8)
        glClearColor(1.0, 1.0, 0.0, 0.0)      # r=255 g=255 b=0 a=0
        glClear(GL_COLOR_BUFFER_BIT)
        assert fbo.read_pixel(2, 2) == 0x0000FFFF
        fbo.unbind()

    @pytest.mark.usefixtures('gl_context')
    def test_reuse_when_region_fits_keeps_same_fbo(self):
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is True
        first = fbo.fbo
        # A smaller-or-equal region must reuse the existing texture, not realloc.
        assert fbo.bind(0, 0, 4, 4) is True
        assert fbo.fbo == first
        assert fbo.current_width == 8

    @pytest.mark.usefixtures('gl_context')
    def test_size_is_clamped_to_max(self):
        fbo = SelectionFBO(max_width=4, max_height=4)
        assert fbo.bind(0, 0, 100, 100) is True
        assert fbo.current_width == 4
        assert fbo.current_height == 4

    @pytest.mark.usefixtures('gl_context')
    def test_incomplete_framebuffer_reported_as_failure(self, monkeypatch):
        # A driver returning an incomplete status must make bind() fail and leave
        # no resources bound/initialized.
        monkeypatch.setattr(selectionbuffers, 'glCheckFramebufferStatus',
                            lambda _target: 0)
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is False
        assert fbo._initialized is False
        assert fbo.fbo is None

    @pytest.mark.usefixtures('gl_context')
    def test_gl_error_during_creation_is_caught(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("simulated driver failure")
        monkeypatch.setattr(selectionbuffers, 'glTexImage2D', boom)
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is False
        assert fbo._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_cleanup_swallows_delete_errors(self, monkeypatch):
        fbo = SelectionFBO()
        assert fbo.bind(0, 0, 8, 8) is True
        monkeypatch.setattr(selectionbuffers, 'glDeleteFramebuffers',
                            lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(selectionbuffers, 'glDeleteTextures',
                            lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(selectionbuffers, 'glDeleteRenderbuffers',
                            lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
        fbo._cleanup()   # must not raise despite every delete throwing
        assert fbo.fbo is None
        assert fbo.color_texture is None
        assert fbo.depth_renderbuffer is None
        assert fbo._initialized is False


def glCheckFramebufferComplete():
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE


# --------------------------------------------------------------------------- #
# SelectionBufferFBO
# --------------------------------------------------------------------------- #
class TestSelectionBufferFBO:
    def test_initial_state(self):
        sb = SelectionBufferFBO()
        assert sb.fbo is None
        assert sb.id_texture is None
        assert sb._initialized is False
        assert sb.id_map == {}

    @pytest.mark.usefixtures('gl_context')
    def test_ensure_size_rejects_zero(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(0, 0) is False
        assert sb._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_ensure_size_creates_mrt_and_is_complete(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(32, 24) is True
        assert sb.fbo is not None
        assert sb.color_texture is not None
        assert sb.id_texture is not None
        assert sb.depth_renderbuffer is not None
        assert (sb.width, sb.height) == (32, 24)
        assert sb.bind() is True
        assert glCheckFramebufferComplete() is True
        sb.unbind()

    @pytest.mark.usefixtures('gl_context')
    def test_ensure_size_is_idempotent_for_same_size(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(32, 32) is True
        first = sb.fbo
        assert sb.ensure_size(32, 32) is True
        assert sb.fbo == first

    @pytest.mark.usefixtures('gl_context')
    def test_resize_recreates_resources(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is True
        # A different size must run the cleanup+recreate branch, adopting the new
        # dimensions (the driver may recycle the freed FBO name, so the id itself
        # is not a reliable witness -- the size is).
        assert sb.ensure_size(48, 48) is True
        assert (sb.width, sb.height) == (48, 48)
        assert sb._initialized is True

    @pytest.mark.usefixtures('gl_context')
    def test_bind_false_before_init(self):
        sb = SelectionBufferFBO()
        assert sb.bind() is False

    def test_read_pixel_before_init_returns_empty(self):
        sb = SelectionBufferFBO()
        assert sb.read_pixel(1, 1) == (0, 1.0)

    @pytest.mark.usefixtures('gl_context')
    def test_read_pixel_out_of_bounds_returns_empty(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is True
        assert sb.read_pixel(-1, 0) == (0, 1.0)
        assert sb.read_pixel(0, 999) == (0, 1.0)

    @pytest.mark.usefixtures('gl_context')
    def test_read_pixel_decodes_id_and_depth(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is True
        sb.bind()
        glViewport(0, 0, 16, 16)
        glClearColor(0, 0, 0, 0)
        glClear(GL_DEPTH_BUFFER_BIT)
        _fill_id_texture((5, 6, 7, 0))       # id = 5 | 6<<8 | 7<<16
        glDrawBuffers(2, _both_attachments())
        obj_id, depth = sb.read_pixel(8, 8)
        assert obj_id == (5 | (6 << 8) | (7 << 16))
        assert depth == pytest.approx(1.0, abs=1e-3)
        sb.unbind()

    @pytest.mark.usefixtures('gl_context')
    def test_clear_zeroes_the_id_buffer(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is True
        sb.bind()
        glViewport(0, 0, 16, 16)
        _fill_id_texture((9, 9, 9, 9))       # write a non-zero id first
        glDrawBuffers(2, _both_attachments())
        assert sb.read_pixel(8, 8)[0] != 0
        sb.clear()                           # must reset the id attachment to 0
        assert sb.read_pixel(8, 8)[0] == 0
        sb.unbind()

    @pytest.mark.usefixtures('gl_context')
    def test_blit_before_init_is_noop(self):
        """Nothing allocated, so the screen keeps what it had and no GL error
        is left behind."""
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, 96, 96)
        glClearColor(0.0, 0.0, 1.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        while glGetError() != GL_NO_ERROR:
            pass
        sb = SelectionBufferFBO()
        sb.blit_to_screen(96, 96)
        assert glGetError() == GL_NO_ERROR
        assert sb.fbo is None
        raw = glReadPixels(48, 48, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
        px = np.frombuffer(bytes(raw), dtype=np.uint8).ravel()
        assert tuple(px[:3]) == (0, 0, 255)

    @pytest.mark.usefixtures('gl_context')
    def test_blit_copies_scene_colour_to_default_framebuffer(self):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(96, 96) is True
        sb.bind()
        glViewport(0, 0, 96, 96)
        glDrawBuffers(1, [GL_COLOR_ATTACHMENT0])   # scene colour attachment
        glClearColor(1.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        glDrawBuffers(2, _both_attachments())
        sb.blit_to_screen(96, 96)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, 96, 96)
        raw = glReadPixels(48, 48, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
        px = np.frombuffer(bytes(raw), dtype=np.uint8).ravel()
        assert px[0] == 255 and px[1] == 0 and px[2] == 0

    def test_set_id_map(self):
        sb = SelectionBufferFBO()
        mapping = {42: ['a', 'b']}
        sb.set_id_map(mapping)
        assert sb.id_map is mapping

    @pytest.mark.usefixtures('gl_context')
    def test_incomplete_framebuffer_reported_as_failure(self, monkeypatch):
        monkeypatch.setattr(selectionbuffers, 'glCheckFramebufferStatus',
                            lambda _target: 0)
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is False
        assert sb._initialized is False
        assert sb.fbo is None

    @pytest.mark.usefixtures('gl_context')
    def test_gl_error_during_creation_is_caught(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("simulated driver failure")
        monkeypatch.setattr(selectionbuffers, 'glTexImage2D', boom)
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is False
        assert sb._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_cleanup_swallows_delete_errors(self, monkeypatch):
        sb = SelectionBufferFBO()
        assert sb.ensure_size(16, 16) is True

        def raiser(*_a):
            raise RuntimeError("x")
        monkeypatch.setattr(selectionbuffers, 'glDeleteFramebuffers', raiser)
        monkeypatch.setattr(selectionbuffers, 'glDeleteTextures', raiser)
        monkeypatch.setattr(selectionbuffers, 'glDeleteRenderbuffers', raiser)
        sb._cleanup()   # every delete throws; must still fully reset
        assert sb.fbo is None
        assert sb.color_texture is None
        assert sb.id_texture is None
        assert sb.depth_renderbuffer is None
        assert sb._initialized is False


def _both_attachments():
    return [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1]
