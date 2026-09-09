"""GL-call-shape tests for shadow FBO allocation (no real GL context).

The GL entry points are monkeypatched to record calls, so we can assert the
allocation *strategy* (immutable ``glTexStorage*`` vs mutable ``glTexImage*``)
without a driver.
"""
import pytest

from OpenGLContext.passes import shadowmap


class _Recorder:
    def __init__(self):
        self.calls = []

    def make(self, name, ret=1):
        def fn(*args, **kwargs):
            self.calls.append(name)
            return ret
        return fn

    def names(self):
        return [c for c in self.calls]


_PATCHED = [
    'glGenFramebuffers', 'glBindFramebuffer', 'glGenTextures', 'glBindTexture',
    'glTexImage2D', 'glTexImage3D', 'glTexStorage2D', 'glTexStorage3D',
    'glTexParameteri', 'glTexParameterfv', 'glFramebufferTexture2D',
    'glFramebufferTextureLayer', 'glDrawBuffer', 'glReadBuffer', 'glViewport',
    'glClear', 'glEnable',
]


def _patch_gl(monkeypatch):
    rec = _Recorder()
    for name in _PATCHED:
        monkeypatch.setattr(shadowmap, name, rec.make(name), raising=False)
    monkeypatch.setattr(shadowmap, 'glCheckFramebufferStatus',
                        lambda *a: shadowmap.GL_FRAMEBUFFER_COMPLETE, raising=False)
    return rec


class TestCubeImmutableStorage:
    def test_cube_uses_texstorage_not_teximage(self, monkeypatch):
        rec = _patch_gl(monkeypatch)
        cube = shadowmap.ShadowMapCube(512)
        assert cube._ensure(512) is not None
        # 4.16: immutable single-allocation, no per-face mutable glTexImage2D
        assert 'glTexStorage2D' in rec.names()
        assert 'glTexImage2D' not in rec.names()

    def test_cube_storage_allocated_once(self, monkeypatch):
        rec = _patch_gl(monkeypatch)
        cube = shadowmap.ShadowMapCube(256)
        cube._ensure(256)
        # one storage allocation for the whole cube (all six faces), not six
        assert rec.names().count('glTexStorage2D') == 1


class TestArrayImmutableStorage:
    def test_csm_array_uses_texstorage3d(self, monkeypatch):
        rec = _patch_gl(monkeypatch)
        arr = shadowmap.ShadowMapArray(256, 4)
        assert arr._ensure(256, 4) is not None
        assert 'glTexStorage3D' in rec.names()
        assert 'glTexImage3D' not in rec.names()


class TestWhatEnsureAnswers:
    """The names it made, so a caller past it holds them.

    The attributes are Optional because there is a moment before the objects
    exist.  A caller that got past ``_ensure`` is past that moment, and it can
    say so by using what it was handed rather than reading the attributes back
    and hoping.  ``glBindFramebuffer(GL_FRAMEBUFFER, None)`` is what the other
    shape risks.
    """

    def test_the_array_hands_back_its_framebuffer_and_texture(self, monkeypatch):
        _patch_gl(monkeypatch)
        array = shadowmap.ShadowMapArray(256, 4)
        assert array._ensure(256, 4) == (array.fbo, array.depth_texture)

    def test_the_cube_hands_back_its_framebuffer_and_texture(self, monkeypatch):
        _patch_gl(monkeypatch)
        cube = shadowmap.ShadowMapCube(256)
        assert cube._ensure(256) == (cube.fbo, cube.depth_texture)

    def test_the_cube_array_hands_back_its_framebuffer_and_texture(self, monkeypatch):
        _patch_gl(monkeypatch)
        cubes = shadowmap.ShadowMapCubeArray(256, 2)
        assert cubes._ensure(256, 2) == (cubes.fbo, cubes.depth_texture)

    @pytest.mark.parametrize('build,names', [
        (lambda: shadowmap.ShadowMapArray(256, 4), (256, 4)),
        (lambda: shadowmap.ShadowMapCube(256), (256,)),
        (lambda: shadowmap.ShadowMapCubeArray(256, 2), (256, 2)),
    ], ids=['array', 'cube', 'cube-array'])
    def test_a_driver_that_refuses_answers_nothing(self, monkeypatch, build, names):
        _patch_gl(monkeypatch)

        def refuse(*args, **named):
            raise RuntimeError('out of memory')

        monkeypatch.setattr(shadowmap, 'glGenFramebuffers', refuse, raising=False)
        assert build()._ensure(*names) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
