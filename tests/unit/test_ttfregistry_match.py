"""Which installed font a ``FontStyle`` resolves to
(:mod:`OpenGLContext.scenegraph.text.ttfregistry`).

The registry is what the solid and outline 3D fonts ask for a font file, so
these two lookups decide what every polygonal ``Text`` node is drawn in.

Both walk a *preference-ordered* list.  ``FontStyle.family`` is VRML97's own:
the first name the machine has a font for wins, and the names after it are the
fallbacks.  ``DEFAULT_FAMILY_SETS`` is the same idea one level down -- for each
generic family it lists the TrueType classifications to look in, best first, so
that ``TYPEWRITER`` reaches for a monospaced face before it settles for the
plain-serif entry that closes the list.
"""

import pytest
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph.text import ttfregistry


def style(**named):
    return basenodes.FontStyle(**named)


@pytest.fixture
def registry():
    """An empty registry; each test fills in the fonts it wants found.

    ``ttffiles.Registry`` reads ``families`` as
    ``{major: {minor: {fontName: ...}}}`` and ``fonts`` as the general font
    names, which is all these two methods reach.
    """
    return ttfregistry.TTFRegistry()


class TestTheDefaultForAGenericFamily:
    """``defaultFont`` walks DEFAULT_FAMILY_SETS best-classification-first."""

    def test_a_typewriter_family_is_not_answered_with_a_serif(self, registry):
        """The monospaced classification leads the TYPEWRITER list.

        Its last entry is plain serif, which on any machine with a Times-like
        face installed matches something -- so it is only ever the fallback.
        """
        registry.families = {
            'SANS': {'GOTHIC-TYPEWRITER': {'DejaVu Sans Mono': 1}},
            'SERIF-OLD': {'DUTCH-MODERN': {'Times New Roman': 1}},
        }

        assert registry.defaultFont('TYPEWRITER') == 'DejaVu Sans Mono'

    def test_the_fallback_entry_is_still_reached(self, registry):
        """With nothing monospaced installed, TYPEWRITER settles for serif."""
        registry.families = {
            'SERIF-OLD': {'DUTCH-MODERN': {'Times New Roman': 1}},
        }

        assert registry.defaultFont('TYPEWRITER') == 'Times New Roman'

    def test_a_family_with_nothing_installed_says_so(self, registry):
        with pytest.raises(RuntimeError):
            registry.defaultFont('SERIF')

    def test_a_family_nobody_has_a_set_for_says_so(self, registry):
        """A name outside DEFAULT_FAMILY_SETS is a RuntimeError, not a crash."""
        with pytest.raises(RuntimeError):
            registry.defaultFont('WINGDINGS')

    def test_the_memo_is_per_registry(self):
        """One registry's answer does not become another registry's answer."""
        first = ttfregistry.TTFRegistry()
        first.families = {'SANS': {'GOTHIC-TYPEWRITER': {'Lucida Console': 1}}}
        assert first.defaultFont('SANS') == 'Lucida Console'

        second = ttfregistry.TTFRegistry()
        with pytest.raises(RuntimeError):
            second.defaultFont('SANS')


class TestTheFamilyPreferenceList:
    """``fontNameFromStyle`` takes the first name it can resolve."""

    @pytest.fixture
    def registry(self, registry):
        registry.fonts = {'Arial': {}, 'Times': {}}
        return registry

    def test_the_first_name_wins(self, registry):
        assert registry.fontNameFromStyle(style(family=['Arial', 'Times'])) == 'Arial'

    def test_the_order_is_what_decides(self, registry):
        assert registry.fontNameFromStyle(style(family=['Times', 'Arial'])) == 'Times'

    def test_an_unresolvable_name_falls_through_to_the_next(self, registry):
        assert registry.fontNameFromStyle(
            style(family=['Gill Sans', 'Times'])
        ) == 'Times'

    def test_an_unresolvable_name_after_a_match_changes_nothing(self, registry):
        assert registry.fontNameFromStyle(
            style(family=['Arial', 'Gill Sans'])
        ) == 'Arial'

    def test_a_generic_family_is_answered_from_the_default_sets(self, registry):
        registry.families = {'SANS': {'GOTHIC-NEO-GROTESQUE': {'Helvetica': 1}}}

        assert registry.fontNameFromStyle(style(family=['SANS'])) == 'Helvetica'
