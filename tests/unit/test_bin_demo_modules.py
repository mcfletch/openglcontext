"""The demo modules in `OpenGLContext.bin` start, render and exit.

`choosecontext`, `choosefonts` and `keyboardevents` are run with
``python -m``, the way their documentation says to run them: each opens a
window, so what is checked is that the process gets one, draws and leaves
without an exception.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

ROOT = os.path.dirname(str(tests_root(__file__)))

MODULES = ['choosecontext', 'choosefonts', 'keyboardevents']

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


@gl
@pytest.mark.slow
@pytest.mark.parametrize('module', MODULES)
def test_the_demo_runs_and_exits(module, tmp_path):
    env = dict(os.environ)
    env.update(
        OPENGLCONTEXT_BACKEND='glfw',
        OPENGLCONTEXT_HIDDEN='1',
        OPENGLCONTEXT_NO_VSYNC='1',
        OPENGLCONTEXT_AUTO_EXIT_FRAMES='4',
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME=module,
    )
    proc = subprocess.run(
        [sys.executable, '-m', 'OpenGLContext.bin.' + module],
        cwd=ROOT, env=env, timeout=300,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = proc.stdout.decode('utf-8', 'replace')
    assert proc.returncode == 0, output[-3000:]
    assert 'Traceback' not in output, output[-3000:]
    shot = tmp_path / (module + '.png')
    assert shot.exists(), 'no screenshot captured\n' + output[-2000:]
    # A rendered scene compresses to more than a flat frame does.
    assert shot.stat().st_size > 1500, 'blank frame\n' + output[-2000:]
