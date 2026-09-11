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
import os

import pytest

from OpenGLContext import plugins
from OpenGLContext.scenegraph import _basenodes_stub, basenodes


@pytest.fixture(scope='module')
def stub():
    """``(path, expected text)`` for this checkout's registry."""
    return _basenodes_stub.expected(_basenodes_stub.__file__)


def _imports(text):
    """``(module, attribute)`` per ``from ... import ...`` line in the stub.

    Read from the parsed file rather than by matching text: the module
    docstring has a sentence that begins with "from" too.  Includes the
    private bases the dynamically built families derive from, which is what
    makes those declarations resolve.
    """
    import ast

    for statement in ast.parse(text).body:
        if isinstance(statement, ast.ImportFrom) and statement.module:
            for alias in statement.names:
                yield statement.module, alias.name


def _names(text):
    """What the stub exports, read from its ``__all__``.

    ``__all__`` rather than the import lines, because that is the list a
    checker expands ``from basenodes import *`` against, and a family built
    with ``type()`` is declared as a class rather than imported.
    """
    import ast

    for statement in ast.parse(text).body:
        if isinstance(statement, ast.Assign):
            targets = [t.id for t in statement.targets if isinstance(t, ast.Name)]
            if '__all__' in targets:
                return {element.value for element in statement.value.elts}
    raise AssertionError('the stub declares no __all__')


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


class TestReadingTheRegistrations:
    """What the generator makes of the shapes a registration can take."""

    def _pairs(self, source):
        return sorted(_basenodes_stub.registrations(source))

    def test_a_plain_registration(self):
        assert self._pairs("Node( 'Box', 'pkg.box.Box' )") == [('Box', 'pkg.box.Box')]

    def test_a_loop_is_unrolled(self):
        """The shader uniform families are registered one per GLSL suffix."""
        source = (
            "for suffix in ('1f', '2f'):\n"
            "    Node( 'U'+suffix, 'pkg.shaders.U'+suffix )\n"
        )
        assert self._pairs(source) == [
            ('U1f', 'pkg.shaders.U1f'), ('U2f', 'pkg.shaders.U2f'),
        ]

    def test_a_list_iterates_as_a_tuple_does(self):
        source = "for s in ['a']:\n    Node( 'N'+s, 'pkg.m.N'+s )\n"
        assert self._pairs(source) == [('Na', 'pkg.m.Na')]

    def test_calls_that_are_not_registrations_are_ignored(self):
        source = "Loader( 'obj', 'pkg.obj' )\nother.Node( 'X', 'pkg.X' )\n"
        assert self._pairs(source) == []

    def test_a_registration_short_of_arguments_is_ignored(self):
        assert self._pairs("Node( 'Box' )") == []

    def test_a_name_that_cannot_be_spelled_is_reported(self):
        """Silently dropping one would leave a node a checker cannot resolve."""
        with pytest.raises(ValueError):
            self._pairs("Node( NAMES[0], 'pkg.m.C' )")

    def test_it_is_the_call_that_reports_one(self):
        """Rather than whoever iterates the answer later: a generator defers
        the whole reading, so the fault surfaces against a line that did
        nothing but consume it."""
        with pytest.raises(ValueError):
            _basenodes_stub.registrations("Node( NAMES[0], 'pkg.m.C' )")

    def test_the_pairs_can_be_read_more_than_once(self):
        source = "Node( 'Box', 'pkg.box.Box' )"
        found = _basenodes_stub.registrations(source)
        assert list(found) == list(found) == [('Box', 'pkg.box.Box')]

    def test_a_loop_over_something_unreadable_is_reported(self):
        with pytest.raises(ValueError):
            self._pairs("for s in SUFFIXES:\n    Node( 'N'+s, 'pkg.m.N'+s )\n")

    def test_a_loop_unpacking_a_tuple_is_skipped(self):
        """Nothing registers that way; a checker-visible name needs a plain target."""
        source = "for a, b in (('x', 'y'),):\n    Node( 'N'+a, 'pkg.m.N'+a )\n"
        assert self._pairs(source) == []


class TestTheDynamicFamilies:
    """A node built by ``type()`` has no class statement for a checker to read,
    so the stub declares it as the base it was built over."""

    def base(self, module, attribute):
        return _basenodes_stub._dynamic_base(module, attribute)

    def test_a_built_subclass_is_declared_as_its_base(self):
        module, prefix, expected = _basenodes_stub.DYNAMIC_FAMILIES[0]
        assert self.base(module, prefix + '1f') == (module, expected)

    def test_the_base_class_itself_is_not_one_of_them(self):
        """It is written out in its module, so a checker already reads it."""
        module, prefix, _base = _basenodes_stub.DYNAMIC_FAMILIES[0]
        assert self.base(module, prefix) is None

    def test_a_name_from_another_module_is_not_one_either(self):
        _module, prefix, _base = _basenodes_stub.DYNAMIC_FAMILIES[0]
        assert self.base('some.other.module', prefix + '1f') is None

    def test_an_unrelated_name_in_the_family_module_is_not_one(self):
        module, _prefix, _base = _basenodes_stub.DYNAMIC_FAMILIES[0]
        assert self.base(module, 'TextureUniform') is None


class TestFindingThePackage:
    def test_it_walks_up_to_the_package_directory(self):
        found = _basenodes_stub.package_root(_basenodes_stub.__file__)
        assert found.endswith(os.sep + 'OpenGLContext')

    def test_a_path_outside_the_package_is_reported(self):
        with pytest.raises(ValueError):
            _basenodes_stub.package_root(os.sep + 'not-a-package')


class TestTheScript:
    """``scripts/write_basenodes_stub.py``, the maintainer's entry point."""

    @pytest.fixture
    def script(self):
        import importlib.util

        path = os.path.join(
            _basenodes_stub.package_root(_basenodes_stub.__file__),
            os.pardir, 'scripts', 'write_basenodes_stub.py',
        )
        if not os.path.exists(path):
            pytest.skip('running against an installed package, not a checkout')
        spec = importlib.util.spec_from_file_location('_write_stub', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_reports_the_file_as_current(self, script, capsys):
        assert script.main([]) == 0
        assert 'up to date' in capsys.readouterr().out

    def test_check_reports_the_same(self, script, capsys):
        assert script.main(['--check']) == 0
        assert 'up to date' in capsys.readouterr().out


class TestTheImportPathsResolve:
    """A stub naming a class that is not there declares nothing usable."""

    def test_every_imported_name_exists_where_it_is_named(self, stub):
        import importlib

        _path, text = stub
        for module_name, attribute in _imports(text):
            module = importlib.import_module(module_name)
            assert hasattr(module, attribute), '%s.%s' % (module_name, attribute)
