"""The generic render-pass dispatcher hard-depended on the
experimental PBR module -- an unconditional `from ...pbrpass import ...` inside the
core-profile branch. Any import-time fault in the PBR chain then broke plain core
rendering for every user, PBR or not. The selection is now guarded and degrades to
the base core FlatPass.
"""
import sys
import types

import pytest

from OpenGLContext.passes import renderpass, pbrpass
from OpenGLContext.passes.flatcore import FlatPass


class TestCorePassClassSelection:
    def setup_method(self):
        pbrpass._renderer_is_pbr_cache = None

    def teardown_method(self):
        pbrpass._renderer_is_pbr_cache = None

    def test_plain_core_when_vrml97_selected(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'vrml97')
        assert renderpass._core_flatpass_class() is FlatPass

    def test_pbr_pass_when_nothing_selected(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)
        assert renderpass._core_flatpass_class() is pbrpass.PBRPass

    def test_context_class_outranks_its_definition(self):
        # A definition's renderer field always holds a value, so the class
        # attribute has to be read first for a class to ask for VRML97.
        context = types.SimpleNamespace(
            renderer='vrml97',
            contextDefinition=types.SimpleNamespace(renderer='pbr'),
        )
        assert renderpass._core_flatpass_class(context) is FlatPass

    def test_definition_renderer_used_when_class_names_none(self):
        context = types.SimpleNamespace(
            renderer=None,
            contextDefinition=types.SimpleNamespace(renderer='vrml97'),
        )
        assert renderpass._core_flatpass_class(context) is FlatPass

    def test_pbr_pass_when_selected(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
        assert renderpass._core_flatpass_class() is pbrpass.PBRPass

    def test_falls_back_when_pbr_import_broken(self, monkeypatch):
        # Simulate an import-time fault in the PBR chain: a stand-in module with no
        # renderer_is_pbr makes `from pbrpass import renderer_is_pbr` raise.
        broken = types.ModuleType('OpenGLContext.passes.pbrpass')
        monkeypatch.setitem(sys.modules, 'OpenGLContext.passes.pbrpass', broken)
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'pbr')
        # Must not raise, and must degrade to the base core pass.
        assert renderpass._core_flatpass_class() is FlatPass


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
