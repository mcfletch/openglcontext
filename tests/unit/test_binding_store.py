"""Key bindings saved to and loaded from the per-user app-data directory."""

import json

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import bindingstore, modes as movemodes
from OpenGLContext.move.navigation import NavigationManager


class Platform:
    submerged = False


@pytest.fixture
def navigation():
    definition = ContextDefinition(movementModes=[
        movemodes.WalkMode(name='walk'), movemodes.FlyMode(name='fly')])
    return NavigationManager(definition, Platform())


class TestRoundTrip:
    def test_saving_then_loading_restores_a_rebinding(self, navigation, tmp_path):
        path = str(tmp_path / 'keys.json')
        navigation.rebind('walk', 'forward', ['t'])
        bindingstore.save_bindings(navigation, path)
        navigation.rebind('walk', 'forward', ['w'])
        assert bindingstore.load_bindings(navigation, path)
        assert navigation.modes()[0].keys_for('forward') == ('t',)

    def test_a_modifier_survives_the_round_trip(self, navigation, tmp_path):
        path = str(tmp_path / 'keys.json')
        bindingstore.save_bindings(navigation, path)
        for _name, binding in navigation.binding_table():
            binding.modifier = ''
        assert bindingstore.load_bindings(navigation, path)
        modifiers = {binding.command: binding.modifier
                     for _name, binding in navigation.binding_table()}
        assert modifiers['lookup'] == 'ctrl'

    def test_loading_a_file_that_is_not_there_changes_nothing(self, navigation,
                                                              tmp_path):
        assert not bindingstore.load_bindings(navigation,
                                              str(tmp_path / 'absent.json'))
        assert navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_a_corrupt_file_is_ignored_rather_than_fatal(self, navigation,
                                                         tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text('not json at all')
        assert not bindingstore.load_bindings(navigation, str(path))
        assert navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_a_command_the_build_no_longer_has_is_skipped(self, navigation,
                                                          tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps(
            {'walk': {'noSuchCommand': {'keys': ['z'], 'modifier': ''}}}))
        assert bindingstore.load_bindings(navigation, str(path))
        assert navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_a_mode_the_build_no_longer_has_is_skipped(self, navigation,
                                                       tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps(
            {'submarine': {'forward': {'keys': ['z'], 'modifier': ''}}}))
        assert bindingstore.load_bindings(navigation, str(path))

    def test_the_file_is_readable_json(self, navigation, tmp_path):
        """Someone will edit this by hand; it should not fight them."""
        path = str(tmp_path / 'keys.json')
        bindingstore.save_bindings(navigation, path)
        stored = json.loads(open(path).read())
        assert stored['walk']['forward']['keys'] == ['w', '<up>']

    def test_saving_creates_the_directory(self, navigation, tmp_path):
        path = str(tmp_path / 'nested' / 'deeper' / 'keys.json')
        bindingstore.save_bindings(navigation, path)
        assert json.loads(open(path).read())


class TestDefaultLocation:
    def test_the_default_path_is_under_the_app_data_directory(self):
        path = bindingstore.bindings_path()
        assert path.endswith(bindingstore.BINDINGS_FILE)
        assert 'OpenGLContext' in path

    def test_a_named_directory_is_used_as_given(self, tmp_path):
        assert bindingstore.bindings_path(str(tmp_path)).startswith(str(tmp_path))


class TestReset:
    def test_reset_puts_every_binding_back(self, navigation):
        navigation.rebind('walk', 'forward', ['t'])
        bindingstore.reset_bindings(navigation)
        assert navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_reset_forgets_the_saved_file_too(self, navigation, tmp_path):
        path = str(tmp_path / 'keys.json')
        navigation.rebind('walk', 'forward', ['t'])
        bindingstore.save_bindings(navigation, path)
        bindingstore.reset_bindings(navigation, path)
        assert not bindingstore.load_bindings(navigation, path)
        assert navigation.modes()[0].keys_for('forward') == ('w', '<up>')


class TestConflicts:
    def test_a_key_already_bound_in_the_same_mode_is_reported(self, navigation):
        table = navigation.binding_table()
        found = bindingstore.conflicts(table, 'w', '', mode='walk')
        assert [name for name, _binding in found] == ['walk']

    def test_the_same_key_in_another_mode_is_not_a_conflict(self, navigation):
        """Walking and flying are never in force at the same moment."""
        table = navigation.binding_table()
        assert bindingstore.conflicts(table, 'w', '', mode='fly') == [
            (name, binding) for name, binding in table
            if name == 'fly' and 'w' in binding.keys]
        assert all(name == 'fly' for name, _binding
                   in bindingstore.conflicts(table, 'w', '', mode='fly'))

    def test_a_key_bound_nowhere_conflicts_with_nothing(self, navigation):
        assert bindingstore.conflicts(navigation.binding_table(), 'z', '',
                                      mode='walk') == []

    def test_a_binding_does_not_conflict_with_itself(self, navigation):
        table = navigation.binding_table()
        mine = [binding for name, binding in table
                if name == 'walk' and binding.command == 'forward'][0]
        assert bindingstore.conflicts(table, 'w', '', mode='walk',
                                      skip=mine) == []

    def test_the_same_key_with_a_different_modifier_is_not_a_conflict(
            self, navigation):
        """`ctrl`+up tilts the view while up alone walks; both are wanted."""
        table = navigation.binding_table()
        assert bindingstore.conflicts(table, '<up>', 'alt', mode='walk') == []


class TestSavingIsAllOrNothing:
    """The file is replaced, never truncated and then rewritten.

    What is at stake is every binding the player has: a save interrupted
    half-way leaves a file that will not parse, and loading reports that by
    logging a warning and silently starting from the defaults.
    """

    def test_a_failed_save_leaves_the_previous_file_intact(self, navigation,
                                                           tmp_path,
                                                           monkeypatch):
        path = str(tmp_path / 'keys.json')
        navigation.modes()[0].bindings[0].keys = ['z']
        bindingstore.save_bindings(navigation, path)
        good = open(path).read()

        def explode(*args, **named):
            raise OSError("disk full")

        monkeypatch.setattr(bindingstore.json, 'dump', explode)
        navigation.modes()[0].bindings[0].keys = ['q']
        with pytest.raises(OSError):
            bindingstore.save_bindings(navigation, path)
        assert open(path).read() == good, "the old bindings were destroyed"

    def test_a_failed_save_leaves_no_rubbish_behind(self, navigation, tmp_path,
                                                    monkeypatch):
        path = str(tmp_path / 'keys.json')

        def explode(*args, **named):
            raise OSError("disk full")

        monkeypatch.setattr(bindingstore.json, 'dump', explode)
        with pytest.raises(OSError):
            bindingstore.save_bindings(navigation, path)
        assert list(tmp_path.iterdir()) == []

    def test_the_directory_is_the_users_own(self, navigation, tmp_path):
        import stat
        directory = tmp_path / 'appdata'
        bindingstore.save_bindings(navigation, str(directory / 'keys.json'))
        mode = stat.S_IMODE(directory.stat().st_mode)
        assert not mode & (stat.S_IRWXG | stat.S_IRWXO), oct(mode)


class TestALoadedFileCannotBreakStartup:
    """The file invites hand-editing, so a hand edit must not be fatal.

    Forgiving of a mode or command that has gone, and equally forgiving of a
    value of the wrong shape -- which is the mistake someone editing JSON by
    hand actually makes.
    """

    def test_keys_given_as_a_string_are_refused_not_exploded_into_letters(
            self, navigation, tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps({'walk': {'forward': {'keys': 'wasd'}}}))
        bindingstore.load_bindings(navigation, str(path))
        assert list(navigation.modes()[0].keys_for('forward')) == ['w', '<up>']

    def test_keys_of_the_wrong_type_do_not_raise(self, navigation, tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps({'walk': {'forward': {'keys': 5}}}))
        assert bindingstore.load_bindings(navigation, str(path))
        assert list(navigation.modes()[0].keys_for('forward')) == ['w', '<up>']

    def test_a_modifier_of_the_wrong_type_is_refused(self, navigation, tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps(
            {'walk': {'forward': {'keys': ['j'], 'modifier': ['ctrl']}}}))
        bindingstore.load_bindings(navigation, str(path))
        assert str(navigation.modes()[0].bindings[0].modifier) == ''

    def test_a_modifier_nothing_understands_is_refused(self, navigation,
                                                       tmp_path):
        """An unknown modifier makes a binding permanently unreachable."""
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps(
            {'walk': {'forward': {'keys': ['j'], 'modifier': 'hyper'}}}))
        bindingstore.load_bindings(navigation, str(path))
        assert str(navigation.modes()[0].bindings[0].modifier) == ''

    def test_the_good_entries_still_apply(self, navigation, tmp_path):
        path = tmp_path / 'keys.json'
        path.write_text(json.dumps({'walk': {
            'forward': {'keys': 5},
            'back': {'keys': ['j'], 'modifier': 'shift'},
        }}))
        bindingstore.load_bindings(navigation, str(path))
        mode = navigation.modes()[0]
        assert list(mode.keys_for('forward')) == ['w', '<up>']
        assert list(mode.keys_for('back')) == ['j']
