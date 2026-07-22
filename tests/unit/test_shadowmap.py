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
        assert cube._ensure(512) is True
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
        assert arr._ensure(256, 4) is True
        assert 'glTexStorage3D' in rec.names()
        assert 'glTexImage3D' not in rec.names()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
