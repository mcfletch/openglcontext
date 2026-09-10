"""Constructing a pygame bitmap font
(:mod:`OpenGLContext.scenegraph.text.pygamefont`).

The font is built from a TrueType file at a pixel size.  A caller that already
knows both -- an application caching its own fonts, or the provider handing on
what it matched -- passes them in; anything left out is looked up through the
provider's TTF registry, which is the part that needs fonts scanned.
"""

import pytest

pytest.importorskip('pygame')

from pygame import font as pygame_font                 # noqa: E402

from OpenGLContext.scenegraph.text import fontprovider, pygamefont   # noqa: E402


@pytest.fixture
def font_file():
    path = pygame_font.match_font('dejavusans') or pygame_font.match_font('freesans')
    if not path:
        pytest.skip('no scalable system font to build a pygame font from')
    return path


@pytest.fixture
def no_registry():
    """Run with no TTF registry, as a process that never scanned fonts has."""
    saved = fontprovider.TTFFontProvider.TTFRegistry
    fontprovider.TTFFontProvider.setTTFRegistry(None)
    try:
        yield
    finally:
        fontprovider.TTFFontProvider.setTTFRegistry(saved)


class TestBuildingFromAKnownFile:
    def test_a_file_and_size_need_no_registry(self, no_registry, font_file):
        built = pygamefont.PyGameBitmapFont(filename=font_file, size=18)

        assert built.font.get_height() > 0

    def test_the_file_it_was_built_from_is_recorded(self, no_registry, font_file):
        built = pygamefont.PyGameBitmapFont(filename=font_file, size=18)

        assert built.filename == font_file

    def test_the_size_it_was_built_at_is_recorded(self, no_registry, font_file):
        built = pygamefont.PyGameBitmapFont(filename=font_file, size=18)

        assert built.size == 18

    def test_line_height_follows_the_size(self, no_registry, font_file):
        small = pygamefont.PyGameBitmapFont(filename=font_file, size=10)
        large = pygamefont.PyGameBitmapFont(filename=font_file, size=30)

        assert large.lineHeight() > small.lineHeight()


class TestWithoutARegistry:
    """Matching needs the scanned font metadata, and says so when it has none."""

    def test_match_reports_the_missing_registry(self, no_registry):
        with pytest.raises(RuntimeError):
            pygamefont.PyGameFontProvider.match(None)
