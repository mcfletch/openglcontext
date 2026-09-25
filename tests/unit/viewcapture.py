"""Frames rendered in a child process, for the tests that read them back.

A test about what the whole viewer draws -- its loader, its passes, its
lights -- runs ``oglc-view`` with ``--capture`` and reads the PNG it writes::

    from tests.unit.viewcapture import view_frame

    frame = view_frame([glb, '--no-physics', '--size', '240x240'],
                       str(tmp_path / 'frame.png'))

:func:`run_to_frame` does the same for any command that writes a frame, such
as a demo script under ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR``.

The child needs a GL target, and :func:`gl_available` says whether this
machine has one: where it has none, the test is skipped before anything runs.
Where it has one, a child that runs past its timeout, exits with an error or
writes no frame fails the test, with the child's output in the report.
"""

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

#: The directory the children run in: the project root, above ``tests/``.
PROJECT_ROOT = str(tests_root(__file__).parent)

#: How much of a failed child's output the report carries, from the end.
OUTPUT_TAIL = 4000


def run_to_frame(command: Sequence[str], out: str, *,
                 env: Mapping[str, str] | None = None,
                 timeout: float = 180) -> np.ndarray:
    """The frame ``command`` writes to ``out``, as an ``(h, w, 3)`` int array.

    ``timeout`` is in seconds; ``env`` defaults to this process's environment.
    """
    command = [str(part) for part in command]
    run_child(command, env=env, timeout=timeout)
    if not os.path.exists(out):
        pytest.fail('%s exited cleanly and wrote no frame to %s'
                    % (' '.join(command), out), pytrace=False)
    return read_frame(out)


def run_child(command: Sequence[str], *,
              env: Mapping[str, str] | None = None,
              timeout: float = 180) -> subprocess.CompletedProcess:
    """``command`` run to completion in :data:`PROJECT_ROOT`, with its output.

    Skips where there is no GL target; fails the test where the child runs
    past ``timeout`` seconds or exits with an error.
    """
    if not gl_available():
        pytest.skip('no GL target available')
    command = [str(part) for part in command]
    try:
        result = subprocess.run(command, timeout=timeout, capture_output=True,
                                text=True, cwd=PROJECT_ROOT, env=env)
    except subprocess.TimeoutExpired as expired:
        pytest.fail('%s ran past %ss:\n%s' % (
            ' '.join(command), timeout, _tail(expired.stdout, expired.stderr)),
            pytrace=False)
    if result.returncode != 0:
        pytest.fail('%s exited %d:\n%s' % (
            ' '.join(command), result.returncode,
            _tail(result.stdout, result.stderr)), pytrace=False)
    return result


def view_command(args: Sequence[str]) -> list[str]:
    """The command line running ``oglc-view`` on ``args`` in this interpreter."""
    return [sys.executable, '-m', 'OpenGLContext.bin.view', *map(str, args)]


def view_frame(args: Sequence[str], out: str, *,
               env: Mapping[str, str] | None = None,
               timeout: float = 180) -> np.ndarray:
    """The frame ``oglc-view`` draws for ``args``, captured to ``out``."""
    return run_to_frame(view_command([*args, '--capture', out]), out,
                        env=env, timeout=timeout)


def read_frame(path: str) -> np.ndarray:
    """The PNG at ``path`` as an ``(h, w, 3)`` int array of RGB."""
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB')).astype(int)


def _tail(*streams: str | bytes | None) -> str:
    """The end of a child's output, however much of it there was."""
    text = ''.join(
        stream.decode('utf-8', 'replace') if isinstance(stream, bytes) else stream
        for stream in streams if stream)
    return text[-OUTPUT_TAIL:]
