"""The rotating picture galleries the pages show.

``.. gallery:: showcase`` puts the named gallery on the page: the slides it
declares, one shown at a time, with the caption and credit under each.  What
each gallery holds is declared in ``docs/images/manifest.toml`` beside the
recipe that renders every picture, so the pages and the renderer read the same
list::

    [[gallery]]
    name = "showcase"
    label = "What OpenGLContext draws"
    interval = 6000
    images = ["showcase/glisteel-forest-road", "showcase/chess"]

The markup is what ``_static/gallery.js`` drives and ``_static/gallery.css``
lays out: every slide is in the page, so the first one shows with no
JavaScript, and the script adds the rotation, the controls and the keyboard.

A picture the manifest declares but the tree does not carry is reported and
dropped, so a renamed render is a build message rather than a hole in the page.
"""

from __future__ import annotations

import os
import posixpath
import tomllib
from typing import Any

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.application import Sphinx
from sphinx.util import logging

__all__ = ['gallery', 'GalleryDirective', 'setup']

log = logging.getLogger(__name__)

#: How long each slide is shown for, where the gallery names nothing.
DEFAULT_INTERVAL = 6000


class gallery(nodes.General, nodes.Element):
    """One gallery.  ``slides`` holds what to show; the children are the images.

    The children are ordinary image nodes and are never visited: they are there
    so that Sphinx copies the files into the built set and says where each one
    landed, which is what the visitor writes into the markup.
    """


def read_manifest(path: str) -> dict[str, Any]:
    """The declared pictures and galleries, from ``manifest.toml``."""
    with open(path, 'rb') as handle:
        data = tomllib.load(handle)
    defaults = data.get('defaults', {})
    images = [dict(defaults, **entry) for entry in data.get('image', [])]
    return {
        'images': {entry['id']: entry for entry in images},
        'galleries': {entry['name']: entry for entry in data.get('gallery', [])},
    }


class GalleryDirective(Directive):
    required_arguments = 1
    optional_arguments = 0
    option_spec = {
        'interval': directives.positive_int,
        'class': directives.class_option,
    }

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        name = self.arguments[0].strip()
        path = env.config.gallery_manifest
        if not path or not os.path.isfile(path):
            return [
                self.state.document.reporter.error(
                    'gallery: no manifest at %s' % (path,), line=self.lineno
                )
            ]
        env.note_dependency(path)
        manifest = read_manifest(path)
        declared = manifest['galleries'].get(name)
        if declared is None:
            return [
                self.state.document.reporter.error(
                    'gallery: the manifest declares no gallery %r' % (name,),
                    line=self.lineno,
                )
            ]

        node = gallery()
        node['label'] = declared.get('label', name)
        node['interval'] = self.options.get(
            'interval', declared.get('interval', DEFAULT_INTERVAL)
        )
        node['classes'] = ['gallery-rotate'] + self.options.get('class', [])
        node['slides'] = []
        for image_id in declared.get('images', ()):
            entry = manifest['images'].get(image_id)
            if entry is None:
                log.warning(
                    'gallery %s names an image the manifest does not declare: %s',
                    name,
                    image_id,
                    location=(env.docname, self.lineno),
                )
                continue
            uri = entry['out']
            if not os.path.isfile(os.path.join(env.srcdir, uri)):
                log.warning(
                    'gallery %s: no such picture: %s',
                    name,
                    uri,
                    location=(env.docname, self.lineno),
                )
                continue
            width, height = entry.get('size', (0, 0))
            node['slides'].append(
                {
                    'uri': uri,
                    'alt': entry.get('alt', ''),
                    'caption': entry.get('caption', ''),
                    'credit': entry.get('credit', ''),
                    'width': width,
                    'height': height,
                }
            )
            node += nodes.image(uri=uri, alt=entry.get('alt', ''))
        if not node['slides']:
            return [
                self.state.document.reporter.warning(
                    'gallery %s has no pictures to show' % (name,), line=self.lineno
                )
            ]
        return [node]


def _resolved(builder: Any, uri: str) -> str:
    """Where ``uri`` landed in the built set, as seen from the page being written.

    ``builder.images`` is what the image nodes above put there, and
    ``builder.imgpath`` is the image directory relative to the current page.
    """
    if uri in builder.images:
        return str(posixpath.join(builder.imgpath, builder.images[uri]))
    return uri


def visit_gallery_html(self: Any, node: gallery) -> None:
    slides = node['slides']
    # The slides' own pixel width, so the stylesheet can stop a wide display
    # scaling the pictures up past what they hold.
    width = slides[0]['width']
    self.body.append(
        '<div class="%s" data-interval="%d" style="--slide-width: %dpx" '
        'aria-label="%s">'
        % (
            ' '.join(node['classes']),
            node['interval'],
            width,
            self.attval(node['label']),
        )
    )
    for position, slide in enumerate(slides):
        # The first slide loads with the page and the rest load as the script
        # reaches them, which is what `data-src` names.
        source = 'src' if position == 0 else 'data-src'
        self.body.append('<figure class="slide">')
        self.body.append(
            '<img %s="%s" width="%d" height="%d" alt="%s">'
            % (
                source,
                self.attval(_resolved(self.builder, slide['uri'])),
                slide['width'],
                slide['height'],
                self.attval(slide['alt']),
            )
        )
        # Caption and credit are authored markup -- a caption names a node in
        # <code>, a credit carries &copy; -- so they go through as written.
        credit = slide['credit']
        self.body.append(
            '<figcaption>%s%s</figcaption>'
            % (
                slide['caption'],
                ' <span class="credit">%s</span>' % (credit,) if credit else '',
            )
        )
        self.body.append('</figure>')
    self.body.append('</div>')
    raise nodes.SkipNode


def visit_gallery_text(self: Any, node: gallery) -> None:
    """Every builder but HTML gets the captions as a list."""
    for slide in node['slides']:
        self.add_text('* %s\n' % (slide['alt'] or slide['uri'],))
    raise nodes.SkipNode


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value('gallery_manifest', '', 'env', str)
    app.add_node(
        gallery,
        html=(visit_gallery_html, None),
        text=(visit_gallery_text, None),
        latex=(visit_gallery_text, None),
        man=(visit_gallery_text, None),
        texinfo=(visit_gallery_text, None),
    )
    app.add_directive('gallery', GalleryDirective)
    return {
        'version': '1.0',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
