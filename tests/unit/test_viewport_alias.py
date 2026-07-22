"""The context exposes getViewPort() (width, height) while a render
pass exposes getViewport() (a 4-tuple); the two differ only by capitalisation, so
a mixed-case call used to AttributeError. The context now accepts either spelling,
and the base shadow stubs return None explicitly.
"""
import pytest


class TestViewportAlias:
    def test_context_accepts_both_spellings(self):
        from OpenGLContext.context import Context
        assert Context.getViewport is Context.getViewPort

    def test_alias_returns_dimensions(self):
        from OpenGLContext.context import Context

        class Fake:
            viewportDimensions = (640, 480)
        assert Context.getViewport.__get__(Fake())() == (640, 480)


class TestBaseShadowStubs:
    def test_stubs_return_none(self):
        from OpenGLContext.passes import _flat

        class Fake:
            pass
        f = Fake()
        assert _flat.FlatPass.renderShadowMaps(f, []) is None
        assert _flat.FlatPass.bindShadowUniforms(f) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
