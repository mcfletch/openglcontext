"""Tests for OpenGLContext.testing.process_exit.flush_and_exit.

The regression/capture harness forces process termination from inside a GL
callback. It must flush coverage before doing so, otherwise subprocess coverage
is silently lost. These tests verify both the flush and the hard-exit.
"""

import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.testing.process_exit import flush_and_exit


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
        from OpenGLContext.testing.process_exit import flush_and_exit
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
            from OpenGLContext.testing.process_exit import flush_and_exit
            def covered():
                return 1
            covered()
            flush_and_exit(0)
            """
        )
    )
    result = subprocess.run(
        [sys.executable, '-m', 'coverage', 'run', '--parallel-mode', str(target)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    data_files = list(tmp_path.glob('.coverage.*'))
    assert data_files, "flush_and_exit must persist coverage before hard exit"
