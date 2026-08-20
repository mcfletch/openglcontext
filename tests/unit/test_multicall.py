"""One bundle, several commands, chosen by the name it was run under."""

import os

import pytest

from OpenGLContext.packaging import multicall


def _commands():
    calls = []
    return calls, {
        'drive': lambda: calls.append('drive') or 0,
        'bake': lambda: calls.append('bake') or 3,
    }


def test_the_name_run_under_chooses_the_command():
    calls, commands = _commands()
    assert multicall.run(commands, argv=['/opt/game/bake']) == 3
    assert calls == ['bake']


def test_a_windows_executable_suffix_is_not_part_of_the_name():
    calls, commands = _commands()
    assert multicall.run(commands, argv=[r'C:\Games\Glinting Steel\drive.exe']) == 0
    assert calls == ['drive']


def test_the_suffix_is_matched_whatever_its_case():
    calls, commands = _commands()
    assert multicall.run(commands, argv=[r'C:\Games\drive.EXE']) == 0
    assert calls == ['drive']


def test_the_remaining_arguments_are_left_for_the_command():
    """The command parses its own arguments, and must not see the name twice."""
    seen = []

    def record():
        import sys
        seen.append(list(sys.argv))
        return 0

    assert multicall.run({'drive': record}, argv=['/opt/game/drive', '--laps', '2']) == 0
    assert seen == [['/opt/game/drive', '--laps', '2']]


def test_an_unknown_name_reports_what_there_is(capsys):
    calls, commands = _commands()
    status = multicall.run(commands, argv=['/opt/game/something-else'])
    assert status == 2
    assert calls == []
    message = capsys.readouterr().err
    assert 'something-else' in message
    assert 'bake' in message and 'drive' in message


def test_a_command_that_returns_nothing_succeeded():
    """``main()`` conventionally returns None on success, not 0."""
    assert multicall.run({'drive': lambda: None}, argv=['drive']) == 0


def test_declaring_no_commands_is_refused():
    with pytest.raises(ValueError):
        multicall.run({}, argv=['drive'])


def test_command_name_reads_the_path_it_is_given():
    assert multicall.command_name('/opt/glisteel/bin/oglc-bake') == 'oglc-bake'
    assert multicall.command_name('glisteel.exe') == 'glisteel'


def test_a_command_may_be_named_rather_than_passed():
    """The bundle imports the command it was asked for and no other."""
    assert multicall.run({'pid': 'os:getpid'}, argv=['pid']) == os.getpid()


def test_a_command_named_but_absent_is_an_error_from_the_import():
    with pytest.raises(ImportError):
        multicall.run({'gone': 'no_such_module_at_all:main'}, argv=['gone'])


def test_a_name_without_an_attribute_is_refused():
    with pytest.raises(ValueError, match='module:attribute'):
        multicall.run({'gone': 'OpenGLContext.packaging.multicall'}, argv=['gone'])


def test_modules_are_named_so_a_freezer_can_be_told_about_them():
    commands = {
        'drive': 'glisteel.game:main',
        'bake': lambda: 0,
    }
    assert multicall.command_modules(commands) == ['glisteel.game']
