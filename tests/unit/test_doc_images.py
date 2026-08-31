"""Every picture the documentation shows is there, described, and accounted for.

A page whose ``<img>`` points nowhere is worse than a page with no picture: the
reader sees a broken frame where the evidence was meant to be, and nothing in a
render or a test run notices. Regenerating the tutorials lost `transforms_1`'s
screenshots once, and it was found by opening the page.

So this walks the whole of ``docs/``: every image reference resolves to a file,
every image says what it shows, every file under ``docs/images/`` is claimed by
``docs/images/manifest.toml``, and every gallery block matches the manifest that
generates it. None of it renders anything, so it costs nothing and runs
everywhere.
"""
import os
import re
import tomllib

import pytest

from OpenGLContext.testing.paths import tests_root

HERE = str(tests_root(__file__))
REPO = os.path.dirname(HERE)
DOCS = os.path.join(REPO, 'docs')
IMAGES = os.path.join(DOCS, 'images')
MANIFEST = os.path.join(IMAGES, 'manifest.toml')

#: ``<img ...>``, and the attributes of it, in source order.
IMG = re.compile(r'<img\s([^>]*?)/?>', re.IGNORECASE | re.DOTALL)
ATTRIBUTE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"', re.DOTALL)

#: Directories the manifest owns outright: everything in one is something it
#: rendered, so a file it does not declare is a picture nothing can regenerate.
#: The rest of ``docs/images/`` is older material each page references directly,
#: some of it the manifest's own source images; taking those over is a job the
#: plan describes rather than a rule to enforce today.
MANAGED = {'gallery', 'features'}


def pages():
    """Every HTML page in the documentation, as (relative path, text)."""
    found = []
    for directory, _, names in os.walk(DOCS):
        for name in sorted(names):
            if not name.endswith('.html'):
                continue
            path = os.path.join(directory, name)
            with open(path, encoding='utf8', errors='replace') as handle:
                found.append((os.path.relpath(path, DOCS), handle.read()))
    return found


def images_in(text):
    """(attributes, whole tag) for each ``<img>``, as a dict of attributes."""
    for match in IMG.finditer(text):
        yield dict(ATTRIBUTE.findall(match.group(1))), match.group(0)


def manifest():
    with open(MANIFEST, 'rb') as handle:
        return tomllib.load(handle)


def entries():
    data = manifest()
    defaults = data.get('defaults', {})
    return [dict(defaults, **entry) for entry in data['image']]


PAGES = pages()


class TestEveryPictureIsThere:
    def test_no_page_points_at_a_missing_image(self):
        """The failure a reader sees first, and a test run never does."""
        missing = []
        for page, text in PAGES:
            for attributes, _ in images_in(text):
                source = attributes.get('src') or attributes.get('data-src')
                if not source or source.startswith(('http:', 'https:', 'data:')):
                    continue
                path = os.path.join(DOCS, os.path.dirname(page), source)
                if not os.path.exists(path):
                    missing.append('%s -> %s' % (page, source))
        assert not missing, 'documentation images that do not exist:\n  ' + \
            '\n  '.join(sorted(missing))

    def test_a_declared_size_is_the_size_the_file_is(self):
        """The stylesheet caps a picture at its own pixel width.

        ``max-width: max-content`` stops a wide display scaling a render up into
        a blur, and the ``width``/``height`` attributes are what reserve the
        space before the bytes arrive. A stale pair moves the page as it loads
        and, until then, sizes the box wrongly.
        """
        Image = pytest.importorskip('PIL.Image')
        wrong = []
        for page, text in PAGES:
            for attributes, _ in images_in(text):
                source = attributes.get('src') or attributes.get('data-src')
                if not source:
                    continue
                # HTML wants a plain integer here; a couple of the older pages
                # write a CSS length, which a browser ignores and so does this.
                if not (attributes.get('width', '').isdigit()
                        and attributes.get('height', '').isdigit()):
                    continue
                path = os.path.join(DOCS, os.path.dirname(page), source)
                if not os.path.exists(path):
                    continue        # reported by the test above
                declared = (int(attributes['width']), int(attributes['height']))
                with Image.open(path) as image:
                    if image.size != declared:
                        wrong.append('%s -> %s says %dx%d, is %dx%d'
                                     % ((page, source) + declared + image.size))
        assert not wrong, 'images whose declared size is not their size:\n  ' + \
            '\n  '.join(sorted(wrong))

    def test_every_image_says_what_it_shows(self):
        """Without ``alt`` the picture is not there at all for some readers."""
        silent = []
        for page, text in PAGES:
            for attributes, tag in images_in(text):
                if not attributes.get('alt', '').strip():
                    source = (attributes.get('src') or attributes.get('data-src')
                              or tag[:60])
                    silent.append('%s -> %s' % (page, source))
        assert not silent, 'documentation images with no alt text:\n  ' + \
            '\n  '.join(sorted(silent))


class TestTheManifestAndTheTreeAgree:
    """``docs/images/manifest.toml`` is what regenerates these pictures.

    A picture it does not declare cannot be reproduced when the renderer
    changes, and an entry with no file is a page waiting to break.
    """

    def test_every_declared_picture_exists(self):
        absent = [entry['out'] for entry in entries()
                  if not os.path.exists(os.path.join(DOCS, entry['out']))]
        assert not absent, 'declared but not rendered:\n  ' + '\n  '.join(absent)

    def test_the_managed_directories_hold_nothing_else(self):
        declared = {os.path.normpath(os.path.join(DOCS, entry['out']))
                    for entry in entries()}
        orphans = []
        for top in sorted(MANAGED):
            for directory, _, names in os.walk(os.path.join(IMAGES, top)):
                for name in names:
                    if name.endswith('.json'):     # the sidecar beside each
                        continue
                    path = os.path.normpath(os.path.join(directory, name))
                    if path not in declared:
                        orphans.append(os.path.relpath(path, IMAGES))
        assert not orphans, ('pictures nothing declares, so nothing can '
                             'regenerate:\n  ' + '\n  '.join(sorted(orphans)))

    def test_every_source_a_picture_is_made_from_is_there(self):
        """An entry whose source has gone cannot be rendered again."""
        missing = [(entry['id'], entry['source']) for entry in entries()
                   if entry['producer'] == 'copy'
                   and not os.path.exists(os.path.join(DOCS, entry['source']))]
        assert not missing, 'sources that have gone: %s' % (missing,)

    def test_every_picture_declares_what_is_in_it(self):
        """A render carries the terms of the model in it, so it names them."""
        for entry in entries():
            assert entry.get('licence'), '%s declares no licence' % entry['id']
            assert entry.get('alt'), '%s declares no alt text' % entry['id']

    def test_the_credits_page_covers_the_restricted_models(self):
        """The models deliberately kept out stay named, so nobody re-adds one."""
        with open(os.path.join(IMAGES, 'ATTRIBUTION.md'), encoding='utf8') as handle:
            text = handle.read()
        for model in ('Sponza', 'Duck', 'DragonAttenuation', 'VirtualCity',
                      'DamagedHelmet'):
            assert model in text, '%s is not accounted for in ATTRIBUTION.md' % model


class TestTheGalleriesMatchTheManifest:
    """A gallery block is generated; a hand edit to one is silently overwritten."""

    def test_every_gallery_a_page_includes_is_declared(self):
        names = {gallery['name'] for gallery in manifest()['gallery']}
        for page, text in PAGES:
            for used in re.findall(r'<!-- gallery: ([\w-]+) -->', text):
                assert used in names, '%s includes undeclared gallery %r' % (page, used)

    def test_every_declared_gallery_names_pictures_that_exist(self):
        by_id = {entry['id']: entry for entry in entries()}
        for gallery in manifest()['gallery']:
            assert len(gallery['images']) >= 2, \
                'gallery %s has nothing to rotate' % gallery['name']
            for image_id in gallery['images']:
                assert image_id in by_id, \
                    'gallery %s names undeclared %s' % (gallery['name'], image_id)
                out = os.path.join(DOCS, by_id[image_id]['out'])
                assert os.path.exists(out), '%s is missing' % by_id[image_id]['out']

    def test_a_gallery_shows_its_first_slide_without_javascript(self):
        """The rest carry ``data-src``; the first has to carry ``src``.

        A page read from a checkout over ``file://`` runs with whatever the
        browser allows and fetches nothing, so the picture that shows when
        nothing else works is the one written into the first slide.
        """
        for page, text in PAGES:
            for block in re.findall(
                    r'<!-- gallery: [\w-]+ -->(.*?)<!-- /gallery -->',
                    text, re.DOTALL):
                slides = list(images_in(block))
                if not slides:
                    continue
                first, _ = slides[0]
                assert 'src' in first, \
                    '%s: the first slide would not show without JavaScript' % page

    def test_the_component_is_loaded_by_every_page_that_uses_it(self):
        for page, text in PAGES:
            if '<!-- gallery: ' not in text:
                continue
            assert 'style/gallery.css' in text, '%s has a gallery and no stylesheet' % page
            assert 'js/gallery.js' in text, '%s has a gallery and no script' % page


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
