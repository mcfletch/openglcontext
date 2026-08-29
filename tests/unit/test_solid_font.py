"""Solid (extruded polygonal) text in a core-profile context.

The FontStyle3D fields -- thickness, renderFront/renderBack/renderSides --
describe geometry, so a context asking for them has to be given the solid
provider rather than a screen-space atlas that can only draw flat glyphs.
"""

import pytest

from OpenGLContext.scenegraph.text import fontprovider, fontstyle3d, toolsfont
from OpenGLContext.scenegraph.text import shaderfont  # noqa: F401  registers the atlas provider


class _Mode:
    def __init__(self, shader_mode):
        self.shader_mode = shader_mode


@pytest.fixture
def isolated_registry():
    """Swap in an empty provider registry and restore it afterwards."""
    saved = fontprovider.FontProvider.providers
    fontprovider.FontProvider.providers = {}
    try:
        yield
    finally:
        fontprovider.FontProvider.providers = saved


@pytest.fixture
def solid_style():
    return fontstyle3d.FontStyle3D(
        family=['SANS'],
        size=.3,
        justify="MIDDLE",
        thickness=.25,
        quality=3,
        renderSides=1,
        renderFront=1,
        renderBack=1,
    )


def _stub_font(provider, monkeypatch, name):
    """Answer provider.get without needing a font file on this machine."""
    monkeypatch.setattr(provider, 'get', lambda fontStyle=None, mode=None: name)


def test_solid_provider_selected_in_shader_mode(
    isolated_registry, solid_style, monkeypatch
):
    """A FontStyle3D in a core-profile context gets the solid provider."""
    solid = toolsfont.ToolsSolidFontProvider
    atlas = shaderfont.ShaderFontProvider
    solid.registerProvider(solid)
    atlas.registerProvider(atlas)
    _stub_font(solid, monkeypatch, 'solid')
    _stub_font(atlas, monkeypatch, 'atlas')

    provider, font = fontprovider.FontProvider.getProviderFont(
        solid_style, mode=_Mode(shader_mode=True)
    )

    assert provider is solid
    assert font == 'solid'


def test_outline_provider_skipped_in_shader_mode(
    isolated_registry, solid_style, monkeypatch
):
    """The outline font draws through the fixed-function pipeline only."""
    outline = toolsfont.ToolsOutlineFontProvider
    outline.registerProvider(outline)
    _stub_font(outline, monkeypatch, 'outline')
    solid_style.format = 'outline'

    provider, font = fontprovider.FontProvider.getProviderFont(
        solid_style, mode=_Mode(shader_mode=True)
    )

    assert provider is None
    assert font is None
