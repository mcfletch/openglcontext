"""Tests for OpenGLContext.testing.paths.tests_root.

The helper walks a path's ancestors to find the enclosing ``tests`` directory so
resources at the tests root stay resolvable no matter how deep a test module
sits.
"""

import pytest

from OpenGLContext.testing.paths import tests_root


def test_finds_tests_directory_from_this_module():
    """A test file under tests/unit/ resolves to the tests/ root."""
    root = tests_root(__file__)
    assert root.name == 'tests'
    assert (root / 'unit').is_dir()


def test_finds_nearest_tests_ancestor(tmp_path):
    """The nearest ancestor named ``tests`` wins over a deeper start."""
    deep = tmp_path / 'tests' / 'unit' / 'sub'
    deep.mkdir(parents=True)
    start = deep / 'test_thing.py'
    start.write_text('')
    assert tests_root(start) == (tmp_path / 'tests')


def test_raises_when_no_tests_directory_above(tmp_path):
    """A path with no ``tests`` ancestor raises a clear RuntimeError."""
    start = tmp_path / 'plain' / 'file.py'
    start.parent.mkdir(parents=True)
    start.write_text('')
    with pytest.raises(RuntimeError, match='no tests/ directory'):
        tests_root(start)
