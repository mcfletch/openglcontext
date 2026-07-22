"""Locate the source tree's ``tests/`` directory from any test module.

Tests live in subdirectories of ``tests/`` (e.g. ``tests/unit/``) yet load shared
resources -- ``wrls/``, ``resources/``, ``reference_images/`` -- that stay at the
``tests/`` root. Passing ``__file__`` to :func:`tests_root` returns that root
regardless of how deep the test sits, so a resource is ``tests_root(__file__) /
'wrls' / name`` no matter which directory the test file is moved into. Importing
from the installed package keeps it resolvable both under pytest and when a test
is run directly.
"""
from pathlib import Path


def tests_root(start) -> Path:
    """The nearest ancestor directory named ``tests`` at or above ``start``.

    ``start`` is a path inside the tree, normally a test module's ``__file__``.
    """
    for parent in Path(start).resolve().parents:
        if parent.name == 'tests':
            return parent
    raise RuntimeError('no tests/ directory above %s' % (start,))
