"""Tests for OpenGLContext.processexit.flush_and_exit.

A capture, the regression harness and a game's own bounded run end the process
from inside a GL callback. It must flush what was written -- standard output
and error, and coverage's data -- before doing so, otherwise it is lost. These
tests verify the flushes and the hard exit.
"""

import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.processexit import flush_and_exit
from OpenGLContext.testing import process_exit


def test_flush_and_exit_saves_active_coverage(monkeypatch):
    """When a coverage collector is active, its data is saved before exit."""
    saved = {'called': False}

    class FakeCov:
        def save(self):
            saved['called'] = True

    exited = {'code': None}

    monkeypatch.setattr('os._exit', lambda code: exited.__setitem__('code', code))

    import coverage
    monkeypatch.setattr(coverage.Coverage, 'current', staticmethod(lambda: FakeCov()))

    flush_and_exit(3)

    assert saved['called'] is True
    assert exited['code'] == 3


def test_flush_and_exit_without_coverage(monkeypatch):
    """No active collector -> no crash, still exits with the given code."""
    exited = {'code': None}
    monkeypatch.setattr('os._exit', lambda code: exited.__setitem__('code', code))

    import coverage
    monkeypatch.setattr(coverage.Coverage, 'current', staticmethod(lambda: None))

    flush_and_exit(0)
    assert exited['code'] == 0


def test_flush_and_exit_survives_coverage_error(monkeypatch):
    """A failure while saving coverage is swallowed; the process still exits."""
    exited = {'code': None}
    monkeypatch.setattr('os._exit', lambda code: exited.__setitem__('code', code))

    import coverage

    def boom():
        raise RuntimeError('coverage save exploded')

    monkeypatch.setattr(coverage.Coverage, 'current', staticmethod(boom))

    flush_and_exit(5)
    assert exited['code'] == 5


def test_flush_and_exit_really_terminates():
    """Integration: the process actually exits with the requested code."""
    code = textwrap.dedent(
        """
        from OpenGLContext.processexit import flush_and_exit
        flush_and_exit(7)
        print("should not reach here")
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 7
    assert 'should not reach here' not in result.stdout


def test_flush_and_exit_writes_coverage_file(tmp_path):
    """End-to-end: coverage data is actually written despite the hard exit."""
    pytest.importorskip("coverage")
    target = tmp_path / "target.py"
    target.write_text(
        textwrap.dedent(
            """
            from OpenGLContext.processexit import flush_and_exit
            def covered():
                return 1
            covered()
            flush_and_exit(0)
            """
        )
    )
    # Where the data goes is said here rather than inherited: a COVERAGE_FILE
    # in the environment -- a CI job's, a regression run's -- would otherwise
    # send the child's data file somewhere this test does not look.
    result = subprocess.run(
        [sys.executable, '-m', 'coverage', 'run', '--parallel-mode',
         '--data-file', str(tmp_path / '.coverage'), str(target)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    data_files = list(tmp_path.glob('.coverage.*'))
    assert data_files, "flush_and_exit must persist coverage before hard exit"


def test_what_was_written_reaches_the_pipe():
    """Output buffered for a pipe is written before the process ends."""
    code = textwrap.dedent(
        """
        import sys
        from OpenGLContext.processexit import flush_and_exit
        sys.stdout.write("frame 120 captured")
        sys.stderr.write("and logged")
        flush_and_exit(0)
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == 'frame 120 captured'
    assert result.stderr.endswith('and logged')


def test_a_game_exits_without_importing_the_test_machinery():
    code = textwrap.dedent(
        """
        import sys
        import OpenGLContext.processexit
        print('OpenGLContext.testing' in sys.modules)
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.stdout.strip() == 'False', result.stderr


def test_the_testing_package_names_the_same_helper():
    assert process_exit.flush_and_exit is flush_and_exit
