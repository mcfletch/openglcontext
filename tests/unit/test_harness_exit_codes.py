"""The measuring harnesses keep exit 3 for "no GL here" (subprocess).

A harness's test skips on exit 3, so a harness that answered 3 for its own
failure -- an engine change that breaks it, a backend that will not load --
would turn a broken measurement into a skip. Each harness is run here with a
backend that does not exist: GL is available, the harness cannot build its
context, and it has to end with a traceback and a code other than 0 or 3.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

HELPERS = os.path.join(str(tests_root(__file__)), 'helpers')

#: Each harness and the smallest arguments that reach its context.
HARNESSES = {
    'frame_cost': ('_frame_cost_harness.py', ['4', '2']),
    'instancing': ('_instancing_perf_harness.py', ['on', '4', '2']),
    'zone_cost': ('_zone_cost_harness.py', ['2', 'plain']),
}


@pytest.mark.parametrize('name', sorted(HARNESSES))
def test_a_harness_that_cannot_build_its_context_fails_rather_than_skips(name):
    if not gl_available():
        pytest.skip('no GL context here, so exit 3 is the right answer')
    script, arguments = HARNESSES[name]
    env = dict(os.environ, OPENGLCONTEXT_BACKEND='no-such-backend')
    done = subprocess.run(
        [sys.executable, os.path.join(HELPERS, script), *arguments],
        capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode not in (0, 3), (
        '%s exited %d for a backend that does not exist:\n%s'
        % (script, done.returncode, done.stderr[-2000:]))
    assert 'Traceback' in done.stderr
