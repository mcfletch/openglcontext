"""In-process real-GL lifecycle tests for the shadow-map depth FBOs.

:class:`ShadowMapArray` (directional CSM cascades), :class:`ShadowMapCubeArray`
(packed point-light cubes) and :class:`ShadowMapCube` (single-cube fallback) are
pure GL depth-texture holders. These drive their create / bind / resize /
completeness-check / cleanup lifecycle against a hidden GLFW core context, plus
the driver-defensive branches via monkeypatch. The GL-call-shape (mocked)
assertions live in test_shadowmap.py.
"""

import pytest


from OpenGL.GL import (
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE, GL_MAX_TEXTURE_IMAGE_UNITS, GL_VERSION,
    glCheckFramebufferStatus, glGetIntegerv, glGetString, glViewport,
)

from OpenGLContext.passes import shadowmap
from OpenGLContext.passes.shadowmap import (
    ShadowMapArray, ShadowMapCubeArray, ShadowMapCube,
    _save_target, _restore_target,
)


@pytest.fixture
def gl_context(gl_window):
    """4.1 rather than 3.3: the shadow pass wants the later GLSL."""
    return gl_window('shadowmap', version=(4, 1))


def _complete():
    return int(glCheckFramebufferStatus(GL_FRAMEBUFFER)) == GL_FRAMEBUFFER_COMPLETE


# --------------------------------------------------------------------------- #
# save/restore target helpers
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures('gl_context')
def test_save_and_restore_target_roundtrip():
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
    @pytest.mark.usefixtures('gl_context')
    def test_bind_layer_creates_complete_fbo(self):
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

    @pytest.mark.usefixtures('gl_context')
    def test_resize_recreates_storage(self):
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is True
        assert arr.bind_layer(0, size=256, layers=4) is True   # different -> recreate
        assert (arr.size, arr.layers) == (256, 4)
        arr.cleanup()

    @pytest.mark.usefixtures('gl_context')
    def test_incomplete_fbo_reports_failure(self, monkeypatch):
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda _t: 0)
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is False

    @pytest.mark.usefixtures('gl_context')
    def test_storage_error_is_caught(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("no immutable array storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage3D', boom)
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is False
        assert arr._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_cleanup_swallows_delete_errors(self, monkeypatch):
        arr = ShadowMapArray(size=128, layers=2)
        assert arr.bind_layer(0) is True

        def boom(*_a, **_k):
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
    ver = glGetString(GL_VERSION)
    try:
        major = int(bytes(ver).split(b'.')[0])
    except (TypeError, ValueError):  # pragma: no cover - no version string, or not a number
        return False
    return major >= 4


class TestShadowMapCubeArray:
    @pytest.mark.usefixtures('gl_context')
    def test_bind_face_creates_complete_fbo(self):
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

    @pytest.mark.usefixtures('gl_context')
    def test_resize_recreates(self):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is True
        assert ca.bind_face(0, 0, size=128, num_cubes=2) is True
        assert (ca.size, ca.num_cubes) == (128, 2)
        ca.cleanup()

    @pytest.mark.usefixtures('gl_context')
    def test_incomplete_reports_failure(self, monkeypatch):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda _t: 0)
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is False

    @pytest.mark.usefixtures('gl_context')
    def test_storage_error_is_caught(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("no cube array storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage3D', boom)
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is False
        assert ca._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_cleanup_swallows_delete_errors(self, monkeypatch):
        if not _has_cube_array():
            pytest.skip("no GL 4.0 cube-map-array")
        ca = ShadowMapCubeArray(size=64, num_cubes=1)
        assert ca.bind_face(0, 0) is True

        def boom(*_a, **_k):
            raise RuntimeError("delete failed")
        monkeypatch.setattr(shadowmap, 'glDeleteFramebuffers', boom)
        monkeypatch.setattr(shadowmap, 'glDeleteTextures', boom)
        ca.cleanup()
        assert ca.fbo is None and ca.depth_texture is None


# --------------------------------------------------------------------------- #
# ShadowMapCube (single-cube fallback)
# --------------------------------------------------------------------------- #
class TestShadowMapCube:
    @pytest.mark.usefixtures('gl_context')
    def test_bind_face_creates_complete_fbo(self):
        cube = ShadowMapCube(size=128)
        assert cube.bind_face(0) is True
        assert cube.texture == cube.depth_texture
        assert _complete()
        for face in range(1, 6):
            assert cube.bind_face(face) is True    # remaining faces reuse storage
        cube.unbind()
        cube.cleanup()
        assert cube.depth_texture is None

    @pytest.mark.usefixtures('gl_context')
    def test_resize_recreates(self):
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is True
        assert cube.bind_face(0, size=128) is True
        assert cube.size == 128
        cube.cleanup()

    @pytest.mark.usefixtures('gl_context')
    def test_incomplete_reports_failure(self, monkeypatch):
        monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus', lambda _t: 0)
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is False

    @pytest.mark.usefixtures('gl_context')
    def test_storage_error_is_caught(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("no cube storage")
        monkeypatch.setattr(shadowmap, 'glTexStorage2D', boom)
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is False
        assert cube._initialized is False

    @pytest.mark.usefixtures('gl_context')
    def test_cleanup_swallows_delete_errors(self, monkeypatch):
        cube = ShadowMapCube(size=64)
        assert cube.bind_face(0) is True

        def boom(*_a, **_k):
            raise RuntimeError("delete failed")
        monkeypatch.setattr(shadowmap, 'glDeleteFramebuffers', boom)
        monkeypatch.setattr(shadowmap, 'glDeleteTextures', boom)
        cube.cleanup()
        assert cube.fbo is None and cube.depth_texture is None


@pytest.mark.usefixtures('gl_context')
def test_max_texture_units_available():
    # sanity: the shadow path assumes a real unit budget to pack into
    assert int(glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS)) >= 16


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
