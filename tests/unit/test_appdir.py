"""A Python environment built in one place and run from another."""

import os

import pytest

from OpenGLContext.packaging import appdir


def _can_symlink(tmp_path):
    """Whether this account may create a symlink here.

    A staged environment has one, so the fixture cannot be built without it.
    Windows grants the privilege only to an administrator or with Developer
    Mode on, and asking is the only way to find out.
    """
    probe = tmp_path / 'symlink-probe'
    try:
        os.symlink(str(tmp_path), str(probe))
    except (OSError, NotImplementedError, AttributeError):
        return False
    os.remove(str(probe))
    return True


class TestRelocation:
    """A tree built in one directory has to run from another."""

    def _staged(self, tmp_path):
        if not _can_symlink(tmp_path):
            pytest.skip('this account may not create symlinks')
        stage = tmp_path / 'stage'
        venv = stage / 'opt' / 'game' / 'venv'
        (venv / 'bin').mkdir(parents=True)
        (stage / 'opt' / 'game' / 'python' / 'bin').mkdir(parents=True)
        (stage / 'opt' / 'game' / 'python' / 'bin' / 'python3').write_text('#binary')
        (venv / 'pyvenv.cfg').write_text(
            'home = %s/opt/game/python/bin\ninclude-system-site-packages = false\n'
            % (stage,))
        (venv / 'bin' / 'drive').write_text(
            '#!%s/opt/game/venv/bin/python3\nprint("go")\n' % (stage,))
        os.symlink(str(stage / 'opt' / 'game' / 'python' / 'bin' / 'python3'),
                   str(venv / 'bin' / 'python3'))
        return stage, venv

    def test_the_recorded_paths_become_the_installed_ones(self, tmp_path):
        stage, venv = self._staged(tmp_path)
        appdir.relocate(str(stage), str(stage), '')
        assert (venv / 'pyvenv.cfg').read_text().startswith(
            'home = /opt/game/python/bin')
        assert (venv / 'bin' / 'drive').read_text().startswith(
            '#!/opt/game/venv/bin/python3\n')

    def test_a_symlink_out_of_the_tree_becomes_a_relative_one(self, tmp_path):
        """An absolute link into the build directory is dangling once installed."""
        stage, venv = self._staged(tmp_path)
        appdir.relocate(str(stage), str(stage), '')
        link = os.readlink(str(venv / 'bin' / 'python3'))
        assert not os.path.isabs(link)
        assert os.path.exists(os.path.join(str(venv / 'bin'), link))

    def test_what_was_changed_is_reported(self, tmp_path):
        stage, venv = self._staged(tmp_path)
        changed = appdir.relocate(str(stage), str(stage), '')
        assert sorted(os.path.basename(path) for path in changed) == [
            'drive', 'python3', 'pyvenv.cfg']

    def test_a_staging_directory_named_relatively_still_relocates(
            self, tmp_path, monkeypatch):
        """A venv records where it was made as an absolute path, whatever the
        caller called the directory.  ``oglc-deb``'s own default build
        directory is a relative one, so a relative name that matched nothing
        would leave every shebang and the interpreter symlink pointing into the
        build tree -- a package that installs and cannot run."""
        stage, venv = self._staged(tmp_path)
        monkeypatch.chdir(tmp_path)
        appdir.relocate('stage', 'stage', '')
        assert (venv / 'bin' / 'drive').read_text().startswith(
            '#!/opt/game/venv/bin/python3\n')
        assert (venv / 'pyvenv.cfg').read_text().startswith(
            'home = /opt/game/python/bin')
        assert not os.path.isabs(os.readlink(str(venv / 'bin' / 'python3')))

    def test_a_binary_file_is_left_alone(self, tmp_path):
        """Rewriting a path inside a shared library would corrupt it."""
        stage, venv = self._staged(tmp_path)
        library = venv / 'bin' / 'libthing.so'
        original = b'\x7fELF\x00\x00' + str(stage).encode() + b'\x00padding'
        library.write_bytes(original)
        appdir.relocate(str(stage), str(stage), '')
        assert library.read_bytes() == original


class TestPruning:
    """A game's package has no use for the interpreter's development files."""

    def _runtime(self, tmp_path):
        prefix = tmp_path / 'opt' / 'game'
        for relative in ('python/include/python3.12/Python.h',
                         'python/lib/python3.12/idlelib/__init__.py',
                         'python/lib/python3.12/tkinter/__init__.py',
                         'python/lib/python3.12/json/__init__.py',
                         'python/lib/tcl9.0/init.tcl',
                         'python/bin/idle3.12',
                         'python/bin/python3.12',
                         'venv/lib/python3.12/site-packages/glisteel/game.py'):
            path = prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('x')
        return prefix

    def test_the_headers_and_the_unused_stdlib_go(self, tmp_path):
        prefix = self._runtime(tmp_path)
        appdir.prune(str(prefix))
        assert not (prefix / 'python' / 'include').exists()
        assert not (prefix / 'python' / 'lib' / 'python3.12' / 'idlelib').exists()
        assert not (prefix / 'python' / 'lib' / 'python3.12' / 'tkinter').exists()
        assert not (prefix / 'python' / 'lib' / 'tcl9.0').exists()
        assert not (prefix / 'python' / 'bin' / 'idle3.12').exists()

    def test_the_interpreter_and_the_application_stay(self, tmp_path):
        prefix = self._runtime(tmp_path)
        appdir.prune(str(prefix))
        assert (prefix / 'python' / 'bin' / 'python3.12').exists()
        assert (prefix / 'python' / 'lib' / 'python3.12' / 'json').exists()
        assert (prefix / 'venv' / 'lib' / 'python3.12' / 'site-packages'
                / 'glisteel' / 'game.py').exists()

    def test_what_was_removed_is_reported(self, tmp_path):
        prefix = self._runtime(tmp_path)
        removed = appdir.prune(str(prefix))
        assert any(path.endswith('idlelib') for path in removed)

    def test_a_pattern_matching_nothing_is_not_an_error(self, tmp_path):
        prefix = self._runtime(tmp_path)
        assert appdir.prune(str(prefix), patterns=['python/nothing-here']) == []


class TestKeepingWhatABackendNeeds:
    """Tk is part of the interpreter, so an application using it must say so.

    The other toolkits are wheels in the environment, and nothing prunes those.
    """

    def test_tk_is_not_wanted_by_default(self):
        assert 'python/lib/python*/tkinter' in appdir.prune_patterns()

    def test_an_application_on_tk_keeps_tkinter_and_tcl(self):
        patterns = appdir.prune_patterns(keep=['tk'])
        assert not [p for p in patterns if 'tkinter' in p or p.startswith('python/lib/tcl')]

    def test_what_no_toolkit_can_reach_still_goes(self):
        patterns = appdir.prune_patterns(keep=['tk'])
        assert 'python/include' in patterns
        assert 'python/lib/python*/idlelib' in patterns

    def test_a_backend_with_nothing_in_the_interpreter_changes_nothing(self):
        """Qt, wx and GLFW arrive as wheels, which are never pruned."""
        assert appdir.prune_patterns(keep=['qt', 'wx', 'glfw']) == appdir.prune_patterns()

    def test_a_backend_nobody_has_heard_of_says_so(self):
        with pytest.raises(ValueError) as raised:
            appdir.prune_patterns(keep=['nonesuch'])
        assert 'nonesuch' in str(raised.value)

    def test_a_built_environment_keeps_them(self, tmp_path):
        prefix = tmp_path / 'opt' / 'demo'
        for relative in ('python/lib/python3.12/tkinter/__init__.py',
                         'python/lib/tcl9.0/init.tcl',
                         'python/include/python3.12/Python.h'):
            path = prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('x')
        appdir.prune(str(prefix), patterns=appdir.prune_patterns(keep=['tk']))
        assert (prefix / 'python' / 'lib' / 'python3.12' / 'tkinter').exists()
        assert (prefix / 'python' / 'lib' / 'tcl9.0').exists()
        assert not (prefix / 'python' / 'include').exists()
