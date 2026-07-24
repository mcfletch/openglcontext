"""In-process GL tests for the transmission backdrop buffer.

TransmissionBuffer copies the opaque colour buffer into a mipmapped texture the
PBR shader samples for refraction. These drive the real GL resource lifecycle
(allocate, resize, capture, bind, release) against a hidden GLFW context; the
pure resolve_mode / read-buffer logic is covered in test_transmission_capture.py.
"""
import os

import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.passes import transmission  # noqa: E402
from OpenGLContext.passes.transmission import TransmissionBuffer  # noqa: E402


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
    win = glfw.create_window(64, 64, "transmission", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


class TestResolveMode:
    def test_env_off_forces_off(self, monkeypatch):
        for val in ('off', 'none', '0'):
            monkeypatch.setenv('OPENGLCONTEXT_TRANSMISSION', val)
            assert transmission.resolve_mode('NVIDIA') == 'off'

    def test_env_blend_forces_blend(self, monkeypatch):
        for val in ('blend', 'fake'):
            monkeypatch.setenv('OPENGLCONTEXT_TRANSMISSION', val)
            assert transmission.resolve_mode('NVIDIA') == 'blend'

    def test_env_full_forces_full_even_on_software(self, monkeypatch):
        for val in ('full', 'on', '1'):
            monkeypatch.setenv('OPENGLCONTEXT_TRANSMISSION', val)
            assert transmission.resolve_mode('llvmpipe') == 'full'

    def test_software_renderer_defaults_to_blend(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_TRANSMISSION', raising=False)
        assert transmission.resolve_mode('llvmpipe (LLVM 15)') == 'blend'
        assert transmission.resolve_mode('softpipe') == 'blend'

    def test_hardware_renderer_defaults_to_full(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_TRANSMISSION', raising=False)
        assert transmission.resolve_mode('NVIDIA GeForce RTX') == 'full'


def test_max_lod_reflects_level_count():
    """max_lod is levels-1 and needs no GL context."""
    b = TransmissionBuffer()
    b.levels = 8
    assert b.max_lod == 7.0


class TestEnsureSize:
    def test_allocates_texture_and_mip_levels(self, gl_context):
        b = TransmissionBuffer()
        assert b.ensure_size(64, 32) is True
        assert b.tex is not None
        assert (b.w, b.h) == (64, 32)
        # full mip chain down to 1x1: floor(log2(64)) + 1 = 7
        assert b.levels == 7
        b.release()

    def test_same_size_is_a_noop(self, gl_context):
        b = TransmissionBuffer()
        b.ensure_size(64, 64)
        first = b.tex
        assert b.ensure_size(64, 64) is True
        assert b.tex == first          # no reallocation
        b.release()

    def test_resize_reallocates(self, gl_context):
        b = TransmissionBuffer()
        b.ensure_size(64, 64)
        first = b.tex
        b.ensure_size(32, 16)
        assert b.tex is not None
        assert first is not None
        assert (b.w, b.h) == (32, 16)
        # reallocated to the new dimensions: floor(log2(32)) + 1 = 6 mip levels
        assert b.levels == 6
        b.release()

    def test_zero_dimensions_clamped_to_one(self, gl_context):
        b = TransmissionBuffer()
        assert b.ensure_size(0, 0) is True
        assert (b.w, b.h) == (1, 1)
        assert b.levels == 1
        b.release()


def test_capture_and_bind_roundtrip(gl_context):
    """capture() copies the default framebuffer and bind() activates the unit."""
    from OpenGL.GL import (
        glViewport, glClearColor, glClear, GL_COLOR_BUFFER_BIT,
        glGetIntegerv, GL_ACTIVE_TEXTURE, GL_TEXTURE0,
    )
    glViewport(0, 0, 64, 64)
    glClearColor(0.2, 0.4, 0.6, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    b = TransmissionBuffer()
    b.ensure_size(64, 64)
    b.capture()                        # reads GL_BACK on the default framebuffer
    b.bind()
    # bind() must leave the active unit restored to unit 0
    assert int(glGetIntegerv(GL_ACTIVE_TEXTURE)) == GL_TEXTURE0
    b.release()
    assert b.tex is None


class TestRelease:
    def test_release_without_texture_is_safe(self):
        b = TransmissionBuffer()          # tex is None
        b.release()
        assert b.tex is None

    def test_release_frees_and_clears(self, gl_context):
        b = TransmissionBuffer()
        b.ensure_size(8, 8)
        assert b.tex is not None
        b.release()
        assert b.tex is None

    def test_release_swallows_delete_errors(self, monkeypatch):
        """A GL failure during teardown must not propagate out of release()."""
        b = TransmissionBuffer()
        b.tex = 123

        def boom(_ids):
            raise RuntimeError("delete failed")

        monkeypatch.setattr(transmission, 'glDeleteTextures', boom)
        b.release()                       # must not raise
        assert b.tex is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
