"""PBR housekeeping -- cache the renderer env read, make
transmission_mode a per-instance attribute (not a shared mutable class attr),
name the glass-opacity floor, and keep the test-only uncached draw path out of
the shipped node.
"""
import pytest

from OpenGLContext.passes import pbrpass


class TestRendererEnvCached:
    def test_env_read_once(self, monkeypatch):
        # setattr rather than a bare assignment: pytest then restores the memo
        # afterwards, so this test cannot decide the answer for the rest of the
        # session.  See OpenGLContext.passes.pbrpass.reset_renderer_cache.
        monkeypatch.setattr(pbrpass, '_renderer_is_pbr_cache', None)
        calls = {'n': 0}
        real = pbrpass.os.environ.get

        def counting(key, *a, **k):
            if key == 'OPENGLCONTEXT_RENDERER':
                calls['n'] += 1
            return real(key, *a, **k)
        monkeypatch.setattr(pbrpass.os.environ, 'get', counting)
        pbrpass.renderer_is_pbr()
        pbrpass.renderer_is_pbr()
        pbrpass.renderer_is_pbr()
        assert calls['n'] == 1

    def test_reflects_env_value(self, monkeypatch):
        monkeypatch.setattr(pbrpass, '_renderer_is_pbr_cache', None)
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
        assert pbrpass.renderer_is_pbr() is True
        pbrpass.reset_renderer_cache()
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'other')
        assert pbrpass.renderer_is_pbr() is False


class TestTransmissionModeInstance:
    def test_default_is_off_per_instance(self):
        a = pbrpass.PBRShaderProgram()
        b = pbrpass.PBRShaderProgram()
        assert a.transmission_mode == 'off'
        a.transmission_mode = 'full'
        # setting one instance must not leak into a freshly built one
        assert pbrpass.PBRShaderProgram().transmission_mode == 'off'
        assert b.transmission_mode == 'off'


class TestNamedConstants:
    def test_glass_min_opacity_named(self):
        assert pbrpass.GLASS_MIN_OPACITY == 0.08


class TestDrawUncachedFencedOut:
    def test_production_node_has_no_test_draw_path(self):
        from OpenGLContext.scenegraph import pbrmesh
        assert not hasattr(pbrmesh._MeshGPU, 'draw_uncached')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
