"""The tutorial code blocks, built by Sphinx with their imported names linked.

``docs/_ext/oglc_tutorials.py`` is the half of the linking that needs Sphinx:
it resolves a dotted name against the Python domain, and writes the links when
the page is written as HTML.  ``test_codelinks.py`` holds the half that does not.
"""

import os
import sys

import pytest

sphinx_application = pytest.importorskip('sphinx.application')

from OpenGLContext.testing.paths import tests_root

PROJECT = str(tests_root(__file__).parent)
EXTENSIONS = os.path.join(PROJECT, 'docs', '_ext')

API = """\
.. py:module:: OpenGLContext.loaders.gltf.samples

.. py:function:: sample_model_url(name)

   A model's address.

.. py:module:: OpenGLContext.loaders.gltf

.. py:module:: OpenGLContext.loaders
"""

TUTORIAL = """\
Walkthrough
===========

.. tutorial-imports::

   sample_model_url OpenGLContext.loaders.gltf.sample_model_url

.. tutorial-code:: python

   from OpenGLContext.loaders.gltf import sample_model_url
   sample_model_url('Lantern')
"""


@pytest.fixture
def built(tmp_path, monkeypatch):
    """The two pages above, built to HTML, as the text of ``walkthrough.html``."""
    monkeypatch.syspath_prepend(EXTENSIONS)
    monkeypatch.syspath_prepend(PROJECT)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'conf.py').write_text(
        "extensions = ['oglc_tutorials']\n"
        "primary_domain = 'py'\n"
        "root_doc = 'index'\n"
    )
    (source / 'index.rst').write_text(
        'Index\n=====\n\n.. toctree::\n\n   api\n   walkthrough\n'
    )
    (source / 'api.rst').write_text('API\n===\n\n' + API)
    (source / 'walkthrough.rst').write_text(TUTORIAL)
    out = tmp_path / 'html'
    app = sphinx_application.Sphinx(
        str(source), str(source), str(out), str(tmp_path / 'doctrees'), 'html',
        status=None, warning=None,
    )
    try:
        app.build()
    finally:
        sys.modules.pop('oglc_tutorials', None)
    return (out / 'walkthrough.html').read_text()


def test_an_imported_name_is_linked_to_the_page_that_documents_it(built):
    assert (
        '<a class="code-link" '
        'href="api.html#OpenGLContext.loaders.gltf.samples.sample_model_url">'
        '<span class="n">sample_model_url</span></a>'
    ) in built


def test_every_use_of_the_name_is_linked(built):
    assert built.count('href="api.html#OpenGLContext.loaders.gltf.samples.sample_model_url"') == 2


def test_each_package_of_the_module_path_is_linked(built):
    assert 'href="api.html#module-OpenGLContext.loaders.gltf"' in built
    assert 'href="api.html#module-OpenGLContext.loaders"' in built


def test_a_package_nothing_documents_is_left_as_text(built):
    assert '<span class="nn">OpenGLContext</span>' in built
    assert 'href="api.html#module-OpenGLContext"' not in built
