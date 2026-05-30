"""Tests for font-provider selection ordering.

These verify the on-screen default: shader-compatible (texture-atlas)
providers are preferred over legacy providers (e.g. GLUT) so that text
renders without requiring a GLUT display, in both compatibility and core
profiles.
"""
import pytest

from OpenGLContext.scenegraph.text.fontprovider import FontProvider


class _FakeProvider(FontProvider):
    """A provider that records selection instead of touching OpenGL."""
    format = "bitmap"
    shader_compatible = False

    def __init__(self, name):
        super().__init__()
        self.name = name

    def get(self, fontStyle=None, mode=None):
        return self.name


class _ShaderProvider(_FakeProvider):
    shader_compatible = True


class _Mode:
    def __init__(self, shader_mode):
        self.shader_mode = shader_mode


@pytest.fixture
def isolated_registry():
    """Swap in an empty provider registry and restore it afterwards."""
    saved = FontProvider.providers
    FontProvider.providers = {}
    try:
        yield
    finally:
        FontProvider.providers = saved


def test_shader_provider_preferred_over_glut_in_legacy_mode(isolated_registry):
    """On-screen (non-shader) rendering should pick the texture-atlas provider."""
    glut = _FakeProvider("glut")
    shader = _ShaderProvider("shader")
    # Register GLUT first to prove preference is not just registration order.
    glut.registerProvider(glut)
    shader.registerProvider(shader)

    provider, font = FontProvider.getProviderFont(None, mode=_Mode(shader_mode=False))

    assert provider is shader
    assert font == "shader"


def test_glut_used_as_fallback_when_no_shader_provider(isolated_registry):
    """Without a texture-atlas provider, the legacy provider still works."""
    glut = _FakeProvider("glut")
    glut.registerProvider(glut)

    provider, font = FontProvider.getProviderFont(None, mode=_Mode(shader_mode=False))

    assert provider is glut
    assert font == "glut"


def test_legacy_provider_skipped_in_shader_mode(isolated_registry):
    """Core-profile (shader) mode must not fall back to a GLUT provider."""
    glut = _FakeProvider("glut")
    glut.registerProvider(glut)

    provider, font = FontProvider.getProviderFont(None, mode=_Mode(shader_mode=True))

    assert provider is None
    assert font is None


def test_shader_provider_selected_in_shader_mode(isolated_registry):
    """Shader mode selects the shader-compatible provider."""
    glut = _FakeProvider("glut")
    shader = _ShaderProvider("shader")
    glut.registerProvider(glut)
    shader.registerProvider(shader)

    provider, font = FontProvider.getProviderFont(None, mode=_Mode(shader_mode=True))

    assert provider is shader
    assert font == "shader"
