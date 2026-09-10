"""Which GLUT bitmap font a ``FontStyle`` selects
(:meth:`OpenGLContext.scenegraph.text.glutfont._GLUTFontProvider.match`).

VRML97 gives ``FontStyle.family`` a list of family names *in preference
order*: the first name the browser has a font for is the one to use, and the
names after it are what to fall back to.  GLUT offers four families
(``SERIF``/``ROMAN``, ``SANS``, ``TYPEWRITER``) at a handful of fixed pixel
sizes, so ``match`` picks a family by that order and then the nearest
available size to ``size * scale``.

A style naming nothing GLUT has, or naming no family at all, gets 10-point
Times, which is the closest thing GLUT has to VRML97's default.
"""
import pytest

from OpenGLContext.scenegraph.text.glutfont import GLUTFontProvider

PROVIDER = GLUTFontProvider
FAMILIES = PROVIDER.bitmapFonts


class _FontStyle:
    """The two ``match`` reads of a FontStyle node."""

    def __init__(self, family=(), size=1.0):
        self.family = list(family)
        self.size = size


def _family_of(specifier):
    """Which entry in ``bitmapFonts`` a returned specifier came from."""
    found = {
        name for name, entries in FAMILIES.items()
        for entry, _size in entries if entry == specifier
    }
    assert found, specifier
    return found


class TestTheFirstNameWins:
    """The preference order is the point of the list."""

    @pytest.mark.parametrize('names,expected', [
        (['SANS', 'SERIF'], 'SANS'),
        (['SERIF', 'SANS'], 'SERIF'),
        (['TYPEWRITER', 'SANS', 'SERIF'], 'TYPEWRITER'),
    ])
    def test_the_earlier_name_is_chosen(self, names, expected):
        specifier, _size = PROVIDER.match(_FontStyle(names))
        assert expected in _family_of(specifier)


class TestAnUnknownNameFallsThrough:
    """A name GLUT has nothing for is skipped, not taken as an answer."""

    def test_a_later_known_name_is_still_used(self):
        specifier, _size = PROVIDER.match(_FontStyle(['Gill Sans', 'TYPEWRITER']))
        assert 'TYPEWRITER' in _family_of(specifier)

    def test_an_earlier_known_name_survives_a_later_unknown_one(self):
        specifier, _size = PROVIDER.match(_FontStyle(['TYPEWRITER', 'Gill Sans']))
        assert 'TYPEWRITER' in _family_of(specifier)

    def test_nothing_known_gives_the_default(self):
        specifier, size = PROVIDER.match(_FontStyle(['Gill Sans', 'Comic Sans']))
        assert 'SERIF' in _family_of(specifier)
        assert size == 10

    def test_no_family_at_all_gives_the_default(self):
        specifier, size = PROVIDER.match(_FontStyle([]))
        assert 'SERIF' in _family_of(specifier)
        assert size == 10

    def test_no_font_style_at_all_gives_the_default(self):
        specifier, size = PROVIDER.match(None)
        assert 'SERIF' in _family_of(specifier)
        assert size == 10


class TestTheNearestSizeIsChosen:
    """Within the chosen family, the available size closest to the target."""

    @pytest.mark.parametrize('size,expected', [
        (0.5, 10),   # 6px asked for; 10 is the smallest Helvetica
        (1.0, 12),   # 12px asked for, and there is a 12
        (2.0, 18),   # 24px asked for; 18 is the largest Helvetica
    ])
    def test_helvetica_sizes(self, size, expected):
        _specifier, found = PROVIDER.match(_FontStyle(['SANS'], size=size))
        assert found == expected
