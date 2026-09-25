"""Every picture the documentation shows is there, described, and accounted for.

A page whose picture points nowhere is worse than a page with no picture: the
reader sees a broken frame where the evidence was meant to be, and nothing in a
render or a test run notices. Regenerating the tutorials lost `transforms_1`'s
screenshots once, and it was found by opening the page.

So this walks the whole of ``docs/``: every image reference resolves to a file,
every image says what it shows, every file under ``docs/images/`` is claimed by
``docs/images/manifest.toml``, and every gallery a page shows is one the
manifest declares. None of it renders anything, so it costs nothing and runs
everywhere.
"""
import os
import re
import sys
import tomllib

import pytest

from OpenGLContext.testing.paths import tests_root

HERE = str(tests_root(__file__))
REPO = os.path.dirname(HERE)
DOCS = os.path.join(REPO, 'docs')
IMAGES = os.path.join(DOCS, 'images')
MANIFEST = os.path.join(IMAGES, 'manifest.toml')

#: ``.. image:: uri`` or ``.. figure:: uri``, and the options indented under it.
PICTURE = re.compile(
    r'^(?P<indent>[ ]*)\.\.[ ]+(?:image|figure)::[ ]*(?P<uri>\S+)[ ]*$',
    re.MULTILINE,
)
OPTION = re.compile(r'^[ ]*:([\w-]+):[ ]*(.*)$')

#: ``.. gallery:: name``, which shows a gallery the manifest declares.
GALLERY = re.compile(r'^[ ]*\.\.[ ]+gallery::[ ]*([\w-]+)[ ]*$', re.MULTILINE)

#: Directories the manifest owns outright: everything in one is something it
#: rendered, so a file it does not declare is a picture nothing can regenerate.
#: The rest of ``docs/images/`` is older material each page references directly,
#: some of it the manifest's own source images.
MANAGED = {'gallery', 'features'}

#: Not read: ``_build`` is the built site, and the module pages carry no
#: pictures of their own.
SKIP = {'_build', 'api', '_static', '_templates', '_ext'}


def pages():
    """Every page of the set, as (relative path, text).

    The tutorials are included: they are written from ``tests/*.py`` and the
    screenshots they name are committed beside them, so a lost screenshot is
    exactly the failure this catches.
    """
    found = []
    for directory, names, files in os.walk(DOCS):
        names[:] = [name for name in names if name not in SKIP]
        for name in sorted(files):
            if not name.endswith('.rst'):
                continue
            path = os.path.join(directory, name)
            with open(path, encoding='utf8', errors='replace') as handle:
                found.append((os.path.relpath(path, DOCS), handle.read()))
    return found


def images_in(text):
    """(uri, options) for each picture in a page."""
    lines = text.split('\n')
    for match in PICTURE.finditer(text):
        start = text[: match.start()].count('\n') + 1
        options = {}
        for line in lines[start:]:
            if not line.strip():
                break
            found = OPTION.match(line)
            if not found:
                break
            options[found.group(1)] = found.group(2).strip()
        yield match.group('uri'), options


def manifest():
    with open(MANIFEST, 'rb') as handle:
        return tomllib.load(handle)


def entries():
    data = manifest()
    defaults = data.get('defaults', {})
    return [dict(defaults, **entry) for entry in data['image']]


PAGES = pages()


class TestEveryPictureIsThere:
    def test_the_pages_are_there_to_read(self):
        """A walk that found nothing passes every check under it."""
        assert len(PAGES) > 40

    def test_no_page_points_at_a_missing_image(self):
        """The failure a reader sees first, and a test run never does."""
        missing = []
        for page, text in PAGES:
            for uri, _ in images_in(text):
                if uri.startswith(('http:', 'https:', 'data:')):
                    continue
                if uri.startswith('/'):
                    path = os.path.join(DOCS, uri[1:])
                else:
                    path = os.path.join(DOCS, os.path.dirname(page), uri)
                if not os.path.exists(path):
                    missing.append('%s -> %s' % (page, uri))
        assert not missing, 'documentation images that do not exist:\n  ' + \
            '\n  '.join(sorted(missing))

    def test_every_image_says_what_it_shows(self):
        """Without ``alt`` the picture is not there at all for some readers."""
        silent = [
            '%s -> %s' % (page, uri)
            for page, text in PAGES
            for uri, options in images_in(text)
            if not options.get('alt', '').strip()
        ]
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

    def test_a_declared_size_is_the_size_the_file_is(self):
        """The gallery writes these into the page as the slide's dimensions.

        They reserve the space before the bytes arrive, and the stylesheet caps
        the panel at the picture's own width so a wide display does not scale a
        render up into a blur. A stale pair moves the page as it loads.
        """
        Image = pytest.importorskip('PIL.Image')
        wrong = []
        for entry in entries():
            path = os.path.join(DOCS, entry['out'])
            if not os.path.exists(path):
                continue        # reported by the test above
            declared = tuple(entry['size'])
            with Image.open(path) as image:
                if image.size != declared:
                    wrong.append(
                        '%s says %dx%d, is %dx%d'
                        % ((entry['id'],) + declared + image.size)
                    )
        assert not wrong, 'pictures whose declared size is not their size:\n  ' + \
            '\n  '.join(sorted(wrong))

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
    """A page names a gallery; the manifest says what is in it.

    The slides are written as the page is built (``docs/_ext/oglc_gallery.py``),
    so a page and the manifest cannot disagree about what a gallery holds --
    but a page can name one that was renamed or removed.
    """

    def test_every_gallery_a_page_shows_is_declared(self):
        names = {gallery['name'] for gallery in manifest()['gallery']}
        for page, text in PAGES:
            for used in GALLERY.findall(text):
                assert used in names, '%s shows undeclared gallery %r' % (page, used)

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

    def test_the_component_is_loaded_by_the_set(self):
        """Every page gets the stylesheet and the script, from the configuration."""
        with open(os.path.join(DOCS, 'conf.py'), encoding='utf8') as handle:
            conf = handle.read()
        assert 'gallery.css' in conf
        assert 'gallery.js' in conf
        assert os.path.isfile(os.path.join(DOCS, '_static', 'gallery.css'))
        assert os.path.isfile(os.path.join(DOCS, '_static', 'gallery.js'))


class TestTheGalleryMarkup:
    """What the directive writes into the page.

    A page is as often read from a checkout over ``file://`` as from the
    published site, so the slides are in the page rather than fetched: the
    first one carries ``src`` and shows with no JavaScript at all, and the rest
    carry ``data-src`` for the script to load as it reaches them.
    """

    @pytest.fixture
    def gallery(self):
        sys.path.insert(0, os.path.join(DOCS, '_ext'))
        oglc_gallery = pytest.importorskip('oglc_gallery')
        node = oglc_gallery.gallery()
        node['classes'] = ['gallery-rotate']
        node['label'] = 'What it draws'
        node['interval'] = 6000
        node['slides'] = [
            {
                'uri': 'images/gallery/showcase/one.jpg',
                'alt': 'the first',
                'caption': 'One',
                'credit': 'A game',
                'width': 1200,
                'height': 675,
            },
            {
                'uri': 'images/gallery/showcase/two.jpg',
                'alt': 'the second',
                'caption': 'Two',
                'credit': '',
                'width': 1200,
                'height': 675,
            },
        ]
        return oglc_gallery, node

    def markup(self, gallery):
        oglc_gallery, node = gallery

        class Builder:
            images = {
                'images/gallery/showcase/one.jpg': 'one.jpg',
                'images/gallery/showcase/two.jpg': 'two.jpg',
            }
            imgpath = '_images'

        class Translator:
            builder = Builder()
            body: list = []

            def attval(self, text):
                return str(text).replace('"', '&quot;')

        from docutils import nodes  # noqa: PLC0415 the docs extra's; the gallery fixture skipped without it

        translator = Translator()
        # The visitor writes the whole panel and skips the image nodes under
        # it, which it says by raising.
        with pytest.raises(nodes.SkipNode):
            oglc_gallery.visit_gallery_html(translator, node)
        return ''.join(translator.body)

    def test_the_first_slide_shows_without_javascript(self, gallery):
        html = self.markup(gallery)
        assert '<img src="_images/one.jpg"' in html

    def test_the_rest_load_as_the_script_reaches_them(self, gallery):
        html = self.markup(gallery)
        assert '<img data-src="_images/two.jpg"' in html

    def test_each_slide_says_what_it_shows(self, gallery):
        html = self.markup(gallery)
        assert 'alt="the first"' in html
        assert 'alt="the second"' in html

    def test_the_credit_travels_with_the_caption(self, gallery):
        html = self.markup(gallery)
        assert '<figcaption>One <span class="credit">A game</span></figcaption>' in html
        assert '<figcaption>Two</figcaption>' in html

    def test_the_panel_carries_its_own_width(self, gallery):
        """The stylesheet caps it there, so a wide display does not scale up."""
        html = self.markup(gallery)
        assert '--slide-width: 1200px' in html


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
