"""A link from one page to another has to land where it says.

``docs/physics.html`` sends a reader to ``terrain.html#heightfield``, and a
browser given an anchor it cannot find shows the top of the page instead --
silently, so the reader lands somewhere plausible and never learns they were
sent to the wrong place.  Reorganising the documentation is exactly what breaks
one of these: a section moves to another page and the anchor keeps resolving
right up until it does not.

Only *relative* links are checked.  An ``http(s)`` URL is somebody else's page,
a root-relative one (``/context/…``) is a position on the published site rather
than in this checkout, and a ``../pydoc/`` one is generated from the source
rather than written.
"""
import re

import pytest

from OpenGLContext.testing.paths import tests_root

DOCS = tests_root(__file__).parent / 'docs'

#: ``href="target"``, in any of the quoting the pages use.
HREF = re.compile(r'href=["\']([^"\']+)["\']')

#: ``id="name"``, which is what an anchor has to find.  ``name="…"`` on an
#: anchor element is the older spelling and still resolves in every browser.
ANCHOR = re.compile(r'(?:id|name)=["\']([^"\']+)["\']')


def _pages():
    """Every page of the site, the tutorials included."""
    return sorted(DOCS.glob('*.html')) + sorted(DOCS.glob('tutorials/*.html'))


def _anchors(path):
    return set(ANCHOR.findall(path.read_text(encoding='utf-8', errors='replace')))


def _links(path):
    """(target page, anchor) for each relative link out of this page.

    The anchor is ``''`` for a link to the page as a whole.  A bare ``#name``
    is a link into the page it appears on.
    """
    text = path.read_text(encoding='utf-8', errors='replace')
    for href in HREF.findall(text):
        if '://' in href or href.startswith(('mailto:', 'data:', '/')):
            continue
        target, _, anchor = href.partition('#')
        if not target:
            yield path, anchor
            continue
        resolved = (path.parent / target).resolve()
        yield resolved, anchor


@pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
class TestEveryLinkLandsSomewhere:
    """The pages are the whole site, so both halves of a link are checkable."""

    def test_every_relative_link_names_a_file_that_exists(self):
        """Generated trees (``pydoc/``) are not in the checkout, so skip them."""
        broken = {}
        for page in _pages():
            for target, _anchor in _links(page):
                if 'pydoc' in target.parts or not target.name.endswith('.html'):
                    continue
                if not target.exists():
                    broken.setdefault(page.name, set()).add(target.name)
        assert not broken, (
            'links to a page that is not in docs/: %s'
            % {k: sorted(v) for k, v in broken.items()})

    def test_every_anchor_is_an_id_on_the_page_it_names(self):
        known = {page: _anchors(page) for page in _pages()}
        broken = {}
        for page in _pages():
            for target, anchor in _links(page):
                if not anchor or target not in known:
                    continue
                if anchor not in known[target]:
                    broken.setdefault(page.name, set()).add(
                        '%s#%s' % (target.name, anchor))
        assert not broken, (
            'anchors named in docs/ that no page defines: %s'
            % {k: sorted(v) for k, v in broken.items()})
