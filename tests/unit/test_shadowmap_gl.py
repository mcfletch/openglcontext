"""In-process real-GL lifecycle tests for the shadow-map depth FBOs.

:class:`ShadowMapArray` (directional CSM cascades), :class:`ShadowMapCubeArray`
(packed point-light cubes) and :class:`ShadowMapCube` (single-cube fallback) are
pure GL depth-texture holders. These drive their create / bind / resize /
completeness-check / cleanup lifecycle against a hidden GLFW core context, plus
the driver-defensive branches via monkeypatch. The GL-call-shape (mocked)
assertions live in test_shadowmap.py.
"""
import os

import pytest

glfw = pytest.importorskip("glfw")

from OpenGL.GL import (  # noqa: E402
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE, glCheckFramebufferStatus,
    glGetIntegerv, GL_MAX_TEXTURE_IMAGE_UNITS,
)

from OpenGLContext.passes import shadowmap  # noqa: E402
from OpenGLContext.passes.shadowmap import (  # noqa: E402
    ShadowMapArray, ShadowMapCubeArray, ShadowMapCube,
    _save_target, _restore_target,
)


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    win = glfw.create_window(64, 64, "shadowmap", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


def _complete():
    return int(glCheckFramebufferStatus(GL_FRAMEBUFFER)) == GL_FRAMEBUFFER_COMPLETE


# --------------------------------------------------------------------------- #
# save/restore target helpers
# --------------------------------------------------------------------------- #
def test_save_and_restore_target_roundtrip(gl_context):
    from OpenGL.GL import glViewport
    glViewport(0, 0, 40, 30)
    fbo, viewport = _save_target()
    assert fbo == 0
    assert viewport == (0, 0, 40, 30)
    _restore_target(fbo, viewport)          # must not raise
    _restore_target(fbo, None)              # viewport None branch


# --------------------------------------------------------------------------- #
# ShadowMapArray (directional CSM)
# --------------------------------------------------------------------------- #
class TestShadowMapArray:
    def test_bind_layer_creates_complete_fbo(self, gl_context):
        arr = ShadowMapArray(size=256, layers=4)
        assert arr.bind_layer(0) is True
        assert arr.fbo is not None and arr.depth_texture is not None
        assert arr.texture == arr.depth_texture
        assert _complete()
        # second layer reuses the same allocation (validated-once path)
        assert arr.bind_layer(2) is True
        arr.unbind()
        arr.cleanup()
        assert arr.fbo is None and arr.depth_texture is None

    def test_resize_recreates_storage(self, gl_context):
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is True
        assert arr.bind_layer(0, size=256, layers=4) is True   # different -> recreate
        assert (arr.size, arr.layers) == (256, 4)
        arr.cleanup()

    def test_incomplete_fbo_reports_failure(self, gl_context, monkeypatch):
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda t: 0)
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is False

    def test_storage_error_is_caught(self, gl_context, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no immutable array storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage3D', boom)
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is False
        assert arr._initialized is False

    def test_cleanup_swallows_delete_errors(self, gl_context, monkeypatch):
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is True

        def boom(*a, **k):
            raise RuntimeError("delete failed")
        monkeypatch.setattr(shadowmap, 'glDeleteFramebuffers', boom)
        monkeypatch.setattr(shadowmap, 'glDeleteTextures', boom)
        arr.cleanup()
        assert arr.fbo is None and arr.depth_texture is None
        assert arr._initialized is False


# --------------------------------------------------------------------------- #
# ShadowMapCubeArray (packed point cubes) -- needs GL 4.0 cube-map-array
# --------------------------------------------------------------------------- #
def _has_cube_array():
    from OpenGL.GL import glGetString, GL_VERSION
    ver = glGetString(GL_VERSION)
    try:
        major = int(bytes(ver).split(b'.')[0])
    except Exception:      # pragma: no cover - version string parse fallback
        return False
    return major >= 4


class TestShadowMapCubeArray:
    def test_bind_face_creates_complete_fbo(self, gl_context):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        ca = ShadowMapCubeArray(size=128, num_cubes=2)
        assert ca.bind_face(0, 0) is True
        assert ca.texture == ca.depth_texture
        assert _complete()
        assert ca.bind_face(1, 3) is True       # different cube+face, reuse storage
        ca.unbind()
        ca.cleanup()
        assert ca.depth_texture is None

    def test_resize_recreates(self, gl_context):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is True
        assert ca.bind_face(0, 0, size=128, num_cubes=2) is True
        assert (ca.size, ca.num_cubes) == (128, 2)
        ca.cleanup()

    def test_incomplete_reports_failure(self, gl_context, monkeypatch):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda t: 0)
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is False

    def test_storage_error_is_caught(self, gl_context, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no cube array storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage3D', boom)
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is False
        assert ca._initialized is False

    def test_cleanup_swallows_delete_errors(self, gl_context, monkeypatch):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is True

        def boom(*a, **k):
            raise RuntimeError("delete failed")
        monkeypatch.setattr(shadowmap, 'glDeleteFramebuffers', boom)
        monkeypatch.setattr(shadowmap, 'glDeleteTextures', boom)
        ca.cleanup()
        assert ca.fbo is None and ca.depth_texture is None


# --------------------------------------------------------------------------- #
# ShadowMapCube (single-cube fallback)
# --------------------------------------------------------------------------- #
class TestShadowMapCube:
    def test_bind_face_creates_complete_fbo(self, gl_context):
        cube = ShadowMapCube(size=128)
        assert cube.bind_face(0) is True
        assert cube.texture == cube.depth_texture
        assert _complete()
        for face in range(1, 6):
            assert cube.bind_face(face) is True    # remaining faces reuse storage
        cube.unbind()
        cube.cleanup()
        assert cube.depth_texture is None

    def test_resize_recreates(self, gl_context):
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is True
        assert cube.bind_face(0, size=128) is True
        assert cube.size == 128
        cube.cleanup()

    def test_incomplete_reports_failure(self, gl_context, monkeypatch):
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda t: 0)
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is False

    def test_storage_error_is_caught(self, gl_context, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no cube storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage2D', boom)
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is False
        assert cube._initialized is False

    def test_cleanup_swallows_delete_errors(self, gl_context, monkeypatch):
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is True

        def boom(*a, **k):
            raise RuntimeError("delete failed")
        monkeypatch.setattr(shadowmap, 'glDeleteFramebuffers', boom)
        monkeypatch.setattr(shadowmap, 'glDeleteTextures', boom)
        cube.cleanup()
        assert cube.fbo is None and cube.depth_texture is None


def test_max_texture_units_available(gl_context):
    # sanity: the shadow path assumes a real unit budget to pack into
    assert int(glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS)) >= 16


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
