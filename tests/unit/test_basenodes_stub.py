"""``basenodes.pyi`` declares every registered node
(:mod:`OpenGLContext.scenegraph._basenodes_stub`).

:mod:`OpenGLContext.scenegraph.basenodes` fills its namespace from the plugin
registry at import time, so a checker reading the source finds nothing in it --
and it is the namespace every scenegraph a caller builds goes through.  The
stub declares those names, and these hold the file on disk to the
registrations it is generated from: a node registered without running
``scripts/write_basenodes_stub.py`` fails here rather than reaching a release
as a name nothing can resolve.
"""
import pytest

from OpenGLContext import plugins
from OpenGLContext.scenegraph import _basenodes_stub, basenodes


@pytest.fixture(scope='module')
def stub():
    """``(path, expected text)`` for this checkout's registry."""
    return _basenodes_stub.expected(_basenodes_stub.__file__)


def _declarations(text):
    """``(module, attribute, name)`` per node the stub text declares.

    The ``typing`` import in the header is a ``from`` line too, so what marks
    a declaration is the ``as`` alias every one of them carries.
    """
    for line in text.splitlines():
        if not line.startswith('from ') or ' as ' not in line:
            continue
        module, _, rest = line[len('from '):].partition(' import ')
        attribute, _, name = rest.partition(' as ')
        yield module.strip(), attribute.strip(), name.strip()


def _names(text):
    return {name for _module, _attribute, name in _declarations(text)}


class TestTheFileIsCurrent:
    def test_it_matches_the_registrations(self, stub):
        path, text = stub
        with open(path, encoding='utf-8') as handle:
            current = handle.read()
        assert current == text, (
            '%s is out of date; run scripts/write_basenodes_stub.py' % (path,))


class TestItCoversTheRegistry:
    """Every name the runtime namespace has, the stub declares."""

    def test_every_registered_node_is_declared(self, stub):
        _path, text = stub
        registered = {entry.name for entry in plugins.Node.all()}
        missing = registered - _names(text)
        assert not missing, sorted(missing)

    def test_it_declares_nothing_extra(self, stub):
        _path, text = stub
        registered = {entry.name for entry in plugins.Node.all()}
        extra = _names(text) - registered
        assert not extra, sorted(extra)

    def test_the_names_are_the_ones_the_module_answers_to(self, stub):
        """A declared name has to be reachable on the module itself."""
        _path, text = stub
        for name in sorted(_names(text)):
            assert hasattr(basenodes, name), name


class TestTheImportPathsResolve:
    """A stub naming a class that is not there declares nothing usable."""

    def test_every_declared_class_exists_where_it_is_named(self, stub):
        import importlib

        _path, text = stub
        for module_name, attribute, _name in _declarations(text):
            module = importlib.import_module(module_name)
            assert hasattr(module, attribute), '%s.%s' % (module_name, attribute)
