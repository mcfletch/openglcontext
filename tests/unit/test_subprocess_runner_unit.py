"""Unit tests for OpenGLContext.testing.subprocess_runner.

Covers command construction, the success (non-timeout) Popen path, process-tree
killing with and without psutil, the TestResult status string, and the
TestRunner orchestration (run / run_regression / summary) using a trivial dummy
script instead of a real GL demo.
"""

import subprocess
import sys
import textwrap
import time

import pytest

from OpenGLContext.testing.subprocess_runner import (
    DEFAULT_TIMEOUT,
    build_command,
    kill_process_tree,
    run_test_with_popen,
)
from OpenGLContext.testing.subprocess_runner import TestResult as _TestResult
from OpenGLContext.testing.subprocess_runner import TestRunner as _TestRunner


@pytest.fixture
def ok_script(tmp_path):
    """A trivial script that ignores its args, prints, and exits 0."""
    script = tmp_path / 'ok.py'
    script.write_text('import sys\nprint("hello from dummy")\nsys.exit(0)\n')
    return script


# --------------------------------------------------------------------------
# TestResult
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(returncode=0), 'PASS'),
        (dict(returncode=2), 'SKIP'),
        (dict(returncode=1), 'FAIL'),
        (dict(returncode=124, timed_out=True), 'TIMEOUT'),
    ],
)
def test_result_str_reports_status(kwargs, expected):
    """__str__ prefixes the line with the derived status word."""
    result = _TestResult(script='t.py', stdout='', stderr='', duration=1.25, **kwargs)
    text = str(result)
    assert text.startswith(expected)
    assert 't.py' in text
    assert '1.25s' in text


# --------------------------------------------------------------------------
# build_command
# --------------------------------------------------------------------------


def test_build_command_coverage_uses_parallel_mode_and_source():
    """With coverage the command runs coverage in parallel mode over the source."""
    cmd = build_command('foo.py', with_coverage=True, coverage_source='Pkg')
    assert cmd[:5] == [sys.executable, '-m', 'coverage', 'run', '--parallel-mode']
    assert '--source=Pkg' in cmd
    assert cmd[-1] == 'foo.py'


# --------------------------------------------------------------------------
# run_test_with_popen: success path
# --------------------------------------------------------------------------


def test_run_test_with_popen_captures_success(ok_script):
    """A quick script returns a successful TestResult with captured stdout."""
    result = run_test_with_popen(ok_script, with_coverage=False, timeout=30)
    assert result.success
    assert result.returncode == 0
    assert not result.timed_out
    assert 'hello from dummy' in result.stdout
    assert result.script == 'ok.py'
    assert result.duration >= 0


def test_run_test_with_popen_passes_env_and_args(tmp_path):
    """Environment overrides and extra args reach the subprocess."""
    script = tmp_path / 'echoenv.py'
    script.write_text(
        'import os, sys\n'
        'print("PROFILE=" + os.environ.get("OPENGLCONTEXT_PROFILE", ""))\n'
        'print("ARGS=" + ",".join(sys.argv[1:]))\n'
    )
    result = run_test_with_popen(
        script,
        args=['--foo', '--bar'],
        env={'OPENGLCONTEXT_PROFILE': 'core'},
        with_coverage=False,
    )
    assert 'PROFILE=core' in result.stdout
    assert 'ARGS=--foo,--bar' in result.stdout
    assert result.profile == 'core'


# --------------------------------------------------------------------------
# kill_process_tree
# --------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Whether *pid* is still running.

    Signal 0 is the POSIX way to ask, and Windows has no signal 0 -- os.kill
    there takes only the signals it can turn into a terminate, and refuses the
    question. psutil knows how to ask on either.
    """
    try:
        import psutil
    except ImportError:
        pass
    else:
        return psutil.pid_exists(pid)
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_kill_process_tree_with_psutil_kills_children():
    """kill_process_tree reaps a parent and its spawned grandchild via psutil."""
    pytest.importorskip('psutil')
    spawner = textwrap.dedent(
        """
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        print(child.pid, flush=True)
        time.sleep(30)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, '-c', spawner],
        stdout=subprocess.PIPE,
        text=True,
    )
    child_pid = int(proc.stdout.readline().strip())
    time.sleep(0.3)

    kill_process_tree(proc.pid)

    deadline = time.time() + 5
    while time.time() < deadline and (_pid_alive(proc.pid) or _pid_alive(child_pid)):
        time.sleep(0.05)
    proc.wait(timeout=5)
    assert not _pid_alive(child_pid)


def test_kill_process_tree_tolerates_vanished_processes(monkeypatch):
    """A child or parent that exits between enumeration and kill is ignored."""
    import types

    fake = types.ModuleType('psutil')

    class NoSuchProcess(Exception):
        pass

    class _Vanished:
        def kill(self):
            raise NoSuchProcess()

    class _Process:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=False):
            return [_Vanished()]

        def kill(self):
            raise NoSuchProcess()

    fake.NoSuchProcess = NoSuchProcess  # type: ignore[attr-defined]
    fake.Process = _Process  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'psutil', fake)

    kill_process_tree(4242)  # both kills raise NoSuchProcess and are swallowed


def test_kill_process_tree_without_psutil_uses_signal(monkeypatch):
    """When psutil is unavailable, it falls back to os.kill on the pid."""
    monkeypatch.setitem(sys.modules, 'psutil', None)
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    kill_process_tree(proc.pid)
    proc.wait(timeout=5)
    assert proc.returncode != 0
    # A non-existent pid is swallowed rather than raising.
    kill_process_tree(999999999)


# --------------------------------------------------------------------------
# TestRunner
# --------------------------------------------------------------------------


def test_runner_defaults_test_dir_to_repo_tests():
    """Without a test_dir, the runner points at the source tree's tests/ dir."""
    runner = _TestRunner()
    assert runner.test_dir.name == 'tests'
    assert runner.reference_dir == runner.test_dir / 'reference_images'
    assert runner.default_timeout == DEFAULT_TIMEOUT


def test_runner_run_resolves_relative_script_and_records(tmp_path, ok_script):
    """run() joins a bare name onto test_dir and appends the result."""
    runner = _TestRunner(test_dir=tmp_path, with_coverage=False)
    result = runner.run(ok_script.name, profile='compatibility')
    assert result.success
    assert runner.results == [result]
    assert result.profile == 'compatibility'


def test_runner_run_selects_glfw_backend_for_core(tmp_path):
    """A core profile with no explicit backend auto-selects glfw."""
    script = tmp_path / 'showbackend.py'
    script.write_text(
        'import os\n'
        'print("BACKEND=" + os.environ.get("OPENGLCONTEXT_BACKEND", "none"))\n'
    )
    runner = _TestRunner(test_dir=tmp_path, with_coverage=False)
    result = runner.run(script, profile='core')
    assert 'BACKEND=glfw' in result.stdout


def test_runner_run_honours_explicit_backend(tmp_path):
    """An explicit backend argument overrides the core auto-selection."""
    script = tmp_path / 'showbackend.py'
    script.write_text(
        'import os\n'
        'print("BACKEND=" + os.environ.get("OPENGLCONTEXT_BACKEND", "none"))\n'
    )
    runner = _TestRunner(test_dir=tmp_path, with_coverage=False)
    result = runner.run(script, profile='core', backend='pygame')
    assert 'BACKEND=pygame' in result.stdout


def test_runner_regression_records_then_tests(tmp_path):
    """With no reference present, run_regression records then tests."""
    script = tmp_path / 'dummy.py'
    script.write_text('import sys\nsys.exit(0)\n')
    ref_dir = tmp_path / 'refs'
    runner = _TestRunner(test_dir=tmp_path, reference_dir=ref_dir, with_coverage=False)

    result = runner.run_regression(script, test_name='mytest', timeout=30)

    assert result.success
    # Two runs happened: the record pass and the test pass.
    assert len(runner.results) == 2


def test_runner_regression_returns_early_on_record_failure(tmp_path):
    """If recording the reference fails, that failing result is returned."""
    script = tmp_path / 'fail.py'
    script.write_text('import sys\nsys.exit(1)\n')
    runner = _TestRunner(test_dir=tmp_path, reference_dir=tmp_path / 'refs',
                        with_coverage=False)

    result = runner.run_regression(script, test_name='badtest', timeout=30)

    assert not result.success
    assert len(runner.results) == 1  # never reached the test pass


def test_runner_regression_resolves_relative_script(tmp_path):
    """A bare script name is resolved against the runner's test_dir."""
    (tmp_path / 'dummy.py').write_text('import sys\nsys.exit(0)\n')
    runner = _TestRunner(test_dir=tmp_path, reference_dir=tmp_path / 'refs',
                         with_coverage=False)

    result = runner.run_regression('dummy.py', test_name='reltest', timeout=30)

    assert result.success
    assert result.script == 'dummy.py'


def test_runner_regression_skips_record_when_reference_exists(tmp_path):
    """An existing reference image skips the record pass."""
    script = tmp_path / 'dummy.py'
    script.write_text('import sys\nsys.exit(0)\n')
    ref_dir = tmp_path / 'refs'
    ref_dir.mkdir()
    (ref_dir / 'mytest.png').write_bytes(b'not really a png')
    runner = _TestRunner(test_dir=tmp_path, reference_dir=ref_dir, with_coverage=False)

    runner.run_regression(script, test_name='mytest', timeout=30)

    assert len(runner.results) == 1  # only the test pass


def test_runner_summary_and_print(capsys):
    """summary() buckets results and print_summary reports every category."""
    runner = _TestRunner(with_coverage=False)
    runner.results = [
        _TestResult('pass.py', 0, '', '', 1.0),
        _TestResult('fail.py', 1, '', '', 1.0),
        _TestResult('skip.py', 2, '', '', 1.0),
        _TestResult('slow.py', 124, '', '', 1.0, timed_out=True),
    ]

    summary = runner.summary()
    assert summary['total'] == 4
    assert summary['passed'] == 1
    assert summary['failed'] == 1
    assert summary['skipped'] == 1
    assert summary['timed_out'] == 1
    assert summary['failed_tests'] == ['fail.py']
    assert summary['timed_out_tests'] == ['slow.py']

    runner.print_summary()
    out = capsys.readouterr().out
    assert '1/4 passed' in out
    assert 'fail.py' in out
    assert 'slow.py' in out
    assert 'skip.py' in out
