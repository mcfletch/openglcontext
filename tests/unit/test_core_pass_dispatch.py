"""The generic render-pass dispatcher hard-depended on the
experimental PBR module -- an unconditional `from ...pbrpass import ...` inside the
core-profile branch. Any import-time fault in the PBR chain then broke plain core
rendering for every user, PBR or not. The selection is now guarded and degrades to
the base core FlatPass.
"""
import sys

import pytest

from OpenGLContext.passes import renderpass, pbrpass


class TestCorePassClassSelection:
    def setup_method(self):
        pbrpass._renderer_is_pbr_cache = None

    def teardown_method(self):
        pbrpass._renderer_is_pbr_cache = None

    def test_plain_core_when_not_pbr(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)
        from OpenGLContext.passes.flatcore import FlatPass
        assert renderpass._core_flatpass_class() is FlatPass

    def test_pbr_pass_when_selected(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
        assert renderpass._core_flatpass_class() is pbrpass.PBRPass

    def test_falls_back_when_pbr_import_broken(self, monkeypatch):
        # Simulate an import-time fault in the PBR chain: a stand-in module with no
        # renderer_is_pbr makes `from pbrpass import renderer_is_pbr` raise.
        import types
        broken = types.ModuleType('OpenGLContext.passes.pbrpass')
        monkeypatch.setitem(sys.modules, 'OpenGLContext.passes.pbrpass', broken)
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
        from OpenGLContext.passes.flatcore import FlatPass
        # Must not raise, and must degrade to the base core pass.
        assert renderpass._core_flatpass_class() is FlatPass


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
