"""Timeout process-tree cleanup for the subprocess runner.

A test script that spawns a long-lived grandchild (as GL windows do) must have
its *whole* tree killed on timeout -- not just the direct child, and never the
pytest process itself.
"""

import os
import signal
import textwrap
import time

import pytest

from OpenGLContext.testing import subprocess_runner
from OpenGLContext.testing.subprocess_runner import run_test, run_test_with_popen


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
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _spawner_script(tmp_path):
    """A script that forks a grandchild sleeper, records its pid, then hangs."""
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "spawner.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            open({str(pidfile)!r}, 'w').write(str(child.pid))
            sys.stdout.flush()
            time.sleep(60)
            """
        )
    )
    return script, pidfile


@pytest.mark.parametrize("runner", [run_test, run_test_with_popen])
def test_timeout_kills_grandchild(tmp_path, runner):
    """On timeout the runner reaps the grandchild, not only the direct child."""
    script, pidfile = _spawner_script(tmp_path)

    result = runner(script, timeout=2, with_coverage=False)

    assert result.timed_out is True
    assert result.returncode == 124

    # Give the kill a moment to propagate.
    deadline = time.time() + 5
    grandchild_pid = int(pidfile.read_text().strip())
    while time.time() < deadline and _pid_alive(grandchild_pid):
        time.sleep(0.05)

    if _pid_alive(grandchild_pid):
        try:
            os.kill(grandchild_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        pytest.fail("grandchild process survived the timeout kill")


def test_run_test_never_targets_the_current_process(monkeypatch, tmp_path):
    """Regression for 2.8: the timeout path must never kill os.getpid()."""
    killed = []
    monkeypatch.setattr(subprocess_runner, 'kill_process_tree', lambda pid: killed.append(pid))

    script = tmp_path / "hang.py"
    script.write_text("import time; time.sleep(60)\n")

    result = run_test(script, timeout=1, with_coverage=False)

    assert result.timed_out is True
    assert os.getpid() not in killed, "runner must not kill the pytest process"
    assert killed, "runner should have killed the child process tree"
