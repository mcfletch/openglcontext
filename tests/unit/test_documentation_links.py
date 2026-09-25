"""A link from one page to another has to land where it says.

``docs/physics.rst`` sends a reader to the heightfield section of
``terrain.rst``, and a link that has lost its target is silent in a browser:
the reader lands at the top of some page and never learns they were sent to
the wrong place.  Reorganising the documentation is exactly what breaks one --
a section moves to another page and the label keeps resolving right up until
it does not.

Sphinx reports both of these as it builds, and a build log is not a failing
test.  Only the links the hand-written pages make are checked here; the
generated halves of the set are written from the source and are checked by
the generators' own tests.
"""
import re

import pytest

from OpenGLContext.testing.paths import tests_root

DOCS = tests_root(__file__).parent / 'docs'

#: ``:doc:`text <target>``` or ``:doc:`target```.
DOC = re.compile(r':doc:`(?:[^`<>]*<([^`<>]+)>|([^`<>]+))`')

#: ``:ref:`text <label>``` or ``:ref:`label```.
REF = re.compile(r':ref:`(?:[^`<>]*<([^`<>]+)>|([^`<>]+))`')

#: ``.. _label:`` on a line of its own, which is what a ``:ref:`` finds.
LABEL = re.compile(r'^\.\. _([\w.-]+):\s*$', re.M)

#: Labels Sphinx defines for itself.
BUILT_IN = {'genindex', 'modindex', 'search', 'py-modindex'}

#: The directories written by the generators, which are not in the checkout
#: until the set is built.
GENERATED = ('api/', 'tutorials/', '/api/', '/tutorials/')


def _pages():
    return sorted(DOCS.glob('*.rst'))


def _targets(pattern, text):
    for explicit, bare in pattern.findall(text):
        yield explicit or bare


def _document(target):
    """The document ``target`` names, seen from a page at the top of ``docs/``, without
    its suffix."""
    if target.startswith('/'):
        return target[1:]
    if target.startswith('../'):
        return target[3:]
    return target


@pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
class TestEveryLinkLandsSomewhere:
    def test_every_doc_reference_names_a_page(self):
        broken = []
        for page in _pages():
            text = page.read_text(encoding='utf-8')
            for target in _targets(DOC, text):
                if target.startswith(GENERATED) or target.lstrip('/').startswith(
                    ('api/', 'tutorials/')
                ):
                    continue
                name = _document(target)
                if not (DOCS / ('%s.rst' % (name,))).is_file():
                    broken.append('%s -> %s' % (page.name, target))
        assert not broken, 'links to a page that is not there: %s' % (broken,)

    def test_every_section_reference_names_a_label(self):
        labels = set(BUILT_IN)
        for page in _pages():
            labels.update(LABEL.findall(page.read_text(encoding='utf-8')))
        for page in sorted(DOCS.glob('tutorials/*.rst')):
            labels.update(LABEL.findall(page.read_text(encoding='utf-8')))
        broken = []
        for page in _pages():
            for target in _targets(REF, page.read_text(encoding='utf-8')):
                if target not in labels:
                    broken.append('%s -> %s' % (page.name, target))
        assert not broken, 'links to a section that is not there: %s' % (broken,)

    def test_the_pages_are_there_to_check(self):
        """A check over an empty set passes and says nothing."""
        assert len(_pages()) > 20
