"""Sphinx configuration for the OpenGLContext documentation set.

The narrative pages are written by hand in this directory.  Two directories
beside them are written by generators and are not in version control:

``tutorials/``
    the code walkthroughs, written by ``docbuild.tutorials`` from the
    ``'''`` commentary in ``tests/*.py``.  The screenshots beside them are
    committed; the pages are not.

``api/``
    a page per Python module, written by PyOpenGL's ``directdocs.dumbpydoc``
    from the installed packages -- the engine, the packages it is built from
    and the ones built on it.

``python build-docs.py`` runs both and then calls Sphinx.
"""

import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(HERE, '_ext'))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from OpenGLContext import __version__

project = 'OpenGLContext'
author = 'Mike C. Fletcher and Contributors'
#: The end is the year the set is built, so a rebuild keeps it current and
#: nobody has to remember to.
copyright = '2003-%s, %s' % (datetime.datetime.now(datetime.timezone.utc).year, author)
release = __version__
version = '.'.join(__version__.split('.')[:2])

extensions = [
    'sphinx.ext.extlinks',
    'sphinx.ext.intersphinx',
    'sphinxcontrib.mermaid',
    'oglc_gallery',
    'oglc_sidebar',
    'oglc_tutorials',
]

#: The diagrams are drawn in the reader's browser, from the source written
#: into the page: a build needs no renderer, and a reader with no network --
#: someone reading the page out of a checkout -- sees the source rather than
#: an empty space.  The script itself comes from jsDelivr, pinned to the
#: version the extension names.
mermaid_output_format = 'raw'
mermaid_light_theme = 'default'
mermaid_dark_theme = 'dark'

# `sphinx.ext.viewcode` is deliberately absent: it follows imports into every
# package the engine sits on and writes a highlighted copy of each into the
# set.  The repository is a click away in the header.

templates_path = ['_templates']
exclude_patterns = ['_build', '_ext', 'Thumbs.db', '.DS_Store']

#: The API pages name every module, class and function in the Python domain,
#: so a bare ``Shape`` in any page resolves to the page that documents it.
default_role = 'py:obj'
primary_domain = 'py'

#: Six hundred module pages take a while to write twice.  Sphinx only needs
#: the cross-reference inventory, which it has from the domain directives.
add_module_names = False
python_use_unqualified_type_names = True

#: A code block with no language named is not highlighted rather than guessed
#: at: the pages carry Python, GLSL, JSON, shell sessions and VRML, and a
#: block lexed as the wrong one of those is coloured nonsense.  Every block
#: that wants highlighting names its language.
highlight_language = 'none'

nitpicky = False


def _pyopengl_inventory():
    """Where to read PyOpenGL's inventory from, or None for the published one.

    A checkout that has built PyOpenGL's set has the inventory on disk, and
    reading it there is what makes the links resolve before that set is
    published and on a machine with no network.  The addresses written into
    the page are the published ones either way.
    """
    named = os.environ.get('PYOPENGL_INVENTORY')
    beside = os.path.join(
        os.path.dirname(PACKAGE_ROOT), 'pyopengl', 'docs', '_build', 'html',
        'objects.inv',
    )
    for candidate in ([named] if named else []) + [beside]:
        if os.path.isfile(candidate):
            return (candidate, None)
    return None


#: The published sets these pages link into.  PyOpenGL's own set declares every
#: entry point, so ``glDrawElementsInstanced`` in a page here resolves to the
#: reference page for it; a set that is not reachable leaves the name as text.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pyopengl': ('https://mcfletch.github.io/pyopengl/', _pyopengl_inventory()),
    'simpleparse': ('https://mcfletch.github.io/simpleparse/', None),
}

#: `build-docs.py --no-intersphinx` builds without them, for a machine with no
#: network: the names are then text rather than links.
if os.environ.get('OPENGLCONTEXT_DOCS_NO_INTERSPHINX'):
    intersphinx_mapping = {}

intersphinx_timeout = 10

#: The prose writes its own: "call ``glBegin()``" rather than "call glBegin".
#: A reference adding a second pair is what that would otherwise read as.
add_function_parentheses = False

extlinks = {
    'khronos': ('https://registry.khronos.org/OpenGL/extensions/%s', '%s'),
    'issue': ('https://github.com/mcfletch/openglcontext/issues/%s', 'issue #%s'),
    'gltf': (
        'https://registry.khronos.org/glTF/specs/2.0/Khronos-Extensions/%s.html',
        '%s',
    ),
}

html_theme = 'furo'
html_title = 'OpenGLContext %s' % (version,)
html_static_path = ['_static']
html_css_files = ['oglc.css', 'gallery.css']
html_js_files = ['gallery.js']
html_logo = 'images/context_logo_icon.png'
html_favicon = 'images/context-icon-small.png'

#: Every page would otherwise carry a copy of its own source, which for the
#: generated half of the set is a second copy of the set.
html_copy_source = False
html_show_sourcelink = False

#: Served from `docs/` in the repository as well as from the published site, so
#: the pictures a page names have to resolve the same way in both.
html_baseurl = 'https://mcfletch.github.io/openglcontext/'

#: Where to find the project, shown as badges at the foot of the sidebar.
#: `_templates/sidebar/badges.html` renders these.
PROJECT_LINKS = [
    (
        'https://pypi.org/project/OpenGLContext/',
        'https://img.shields.io/pypi/v/OpenGLContext',
        'OpenGLContext on PyPI',
    ),
    (
        'https://github.com/mcfletch/openglcontext/actions/workflows/test.yml',
        'https://img.shields.io/github/actions/workflow/status'
        '/mcfletch/openglcontext/test.yml?branch=develop&label=tests',
        'The test suite on develop',
    ),
]

#: Where the source is, for the link in the top-right icon row.
PROJECT_URL = 'https://github.com/mcfletch/openglcontext'

html_theme_options = {
    # One button in the top-right icon row.  It is the project link rather
    # than an edit link: `_templates/components/edit-this-page.html` is what
    # the theme includes for it, and that is what it renders.  `source_*` are
    # deliberately unset, since those are what would make it an edit link.
    'top_of_page_buttons': ['edit'],
}

#: What the two templates above read.  A template sees `html_context`, not
#: this module.
html_context = {
    'project_url': PROJECT_URL,
    'project_badges': PROJECT_LINKS,
}

#: Furo's own list, from its `theme.conf`, with the badges added after
#: `scroll-end` so they sit below the navigation rather than scrolling with
#: it.  Naming one sidebar means naming them all.
html_sidebars = {
    '**': [
        'sidebar/brand.html',
        'sidebar/search.html',
        'sidebar/scroll-start.html',
        'sidebar/navigation.html',
        'sidebar/ethical-ads.html',
        'sidebar/scroll-end.html',
        'sidebar/badges.html',
        'sidebar/variant-selector.html',
    ]
}

#: The pictures each gallery shows, and what is in them.  Read by the
#: ``gallery`` directive in ``_ext/oglc_gallery.py``; written, together with
#: the pictures themselves, by the workspace's ``tools/doc_images.py``.
gallery_manifest = os.path.join(HERE, 'images', 'manifest.toml')
