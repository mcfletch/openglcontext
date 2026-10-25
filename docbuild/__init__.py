"""What builds the documentation set, beside the pages themselves.

Two things live here:

:mod:`docbuild.markup`
    the wiki-ish commentary format the tutorial scripts are written in, as
    reStructuredText.

:mod:`docbuild.tutorials`
    the code walkthroughs: each ``tests/tutorials/*/*.py`` script split into
    its commentary and its code, and written as a page, with a page for each
    path through them and an index of the paths.

``build-docs.py`` at the root of the checkout runs it, together with the module
pages, and calls Sphinx over the result.  The package is not part of the
distribution: it is a tool of this repository.
"""
