"""Tests for font-provider selection ordering.

These verify the on-screen default: shader-compatible (texture-atlas)
providers are preferred over legacy providers (e.g. GLUT) so that text
renders without requiring a GLUT display, in both compatibility and core
profiles.

``matchFamily`` is the other half: which of the names in a FontStyle's
preference list a provider ends up serving.
"""
import pytest
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph.text.fontprovider import FontProvider, matchFamily


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


class TestTheFamilyPreferenceList:
    """``matchFamily`` walks ``FontStyle.family`` in the order VRML97 gives it.

    The list is a preference order, so the first name the lookup can answer is
    the font to use and everything after it is a fallback.
    """

    AVAILABLE = {'SANS': 'helvetica', 'SERIF': 'times'}

    def lookup(self, specifier):
        return self.AVAILABLE.get(specifier.upper())

    def style(self, **named):
        return basenodes.FontStyle(**named)

    def test_the_first_name_that_resolves_wins(self):
        assert matchFamily(
            self.style(family=['SANS', 'SERIF']), self.lookup
        ) == 'helvetica'

    def test_the_order_is_what_decides(self):
        assert matchFamily(
            self.style(family=['SERIF', 'SANS']), self.lookup
        ) == 'times'

    def test_a_name_with_no_font_falls_through_to_the_next(self):
        assert matchFamily(
            self.style(family=['Gill Sans', 'SERIF']), self.lookup
        ) == 'times'

    def test_a_later_unknown_name_does_not_displace_an_earlier_match(self):
        assert matchFamily(
            self.style(family=['SERIF', 'Gill Sans']), self.lookup
        ) == 'times'

    def test_nothing_resolvable_gives_none(self):
        assert matchFamily(
            self.style(family=['Gill Sans', 'Comic Sans']), self.lookup
        ) is None

    def test_an_empty_family_gives_none(self):
        assert matchFamily(self.style(family=[]), self.lookup) is None

    def test_no_font_style_at_all_gives_none(self):
        assert matchFamily(None, self.lookup) is None

    def test_the_lookup_is_asked_once_per_name_until_it_answers(self):
        asked = []

        def lookup(specifier):
            asked.append(specifier)
            return self.AVAILABLE.get(specifier.upper())

        matchFamily(self.style(family=['Gill Sans', 'SANS', 'SERIF']), lookup)

        assert asked == ['Gill Sans', 'SANS']
