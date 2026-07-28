"""Tests that GLUT bitmap fonts are only used on a GLUT context.

GLUT bitmap routines segfault when called without a live GLUT context, so the
provider must refuse to select them on non-GLUT backends (e.g. GLFW, pygame)
and fall back to the texture-atlas font.
"""
import pytest

from OpenGLContext.scenegraph.text import glutfont
from OpenGLContext.scenegraph.text.fontprovider import FontProvider


class _Ctx:
    def __init__(self, providesGLUT):
        self.providesGLUT = providesGLUT


class _Mode:
    def __init__(self, providesGLUT, shader_mode=False):
        self.context = _Ctx(providesGLUT)
        self.shader_mode = shader_mode


def test_glutfont_refuses_without_glut_context():
    """GLUTFontProvider.get raises on a non-GLUT context instead of crashing."""
    with pytest.raises(RuntimeError):
        glutfont.GLUTFontProvider.get(None, _Mode(providesGLUT=False))


def test_glutfont_refuses_when_no_context():
    """A missing context (mode=None) is treated as non-GLUT."""
    with pytest.raises(RuntimeError):
        glutfont.GLUTFontProvider.get(None, None)


def test_glutfont_served_on_glut_context():
    """On a GLUT context the provider returns a GLUT bitmap font.

    Construction touches no GLUT entry points, so this is safe without a
    real context.
    """
    font = glutfont.GLUTFontProvider.get(None, _Mode(providesGLUT=True))
    assert isinstance(font, glutfont.GLUTBitmapFont)


def test_provider_selection_skips_glut_on_non_glut_context():
    """getProviderFont falls back past GLUT to the atlas font off-GLUT."""
    selected = []

    class _ShaderProvider(FontProvider):
        format = "bitmap"
        shader_compatible = True

        def get(self, fontStyle=None, mode=None):
            selected.append("shader")
            return "shader-font"

    saved = FontProvider.providers
    FontProvider.providers = {}
    try:
        glutfont.GLUTFontProvider.registerProvider(glutfont.GLUTFontProvider)
        shader = _ShaderProvider()
        shader.registerProvider(shader)

        provider, font = FontProvider.getProviderFont(
            None, mode=_Mode(providesGLUT=False, shader_mode=False)
        )
        assert provider is shader
        assert font == "shader-font"
    finally:
        FontProvider.providers = saved
