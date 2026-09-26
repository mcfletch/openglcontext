"""A GLUT context can be built like any other, not only through ContextMainLoop.

``glutCreateWindow`` before ``glutInit`` is not an error a caller can catch:
freeglut prints

    freeglut ERROR: Function <glutCreateWindow> called without first calling
    'glutInit'.

and calls ``exit()``.  Every way of building a context -- ``ContextMainLoop``,
a test, a view embedded in an application with its own loop, a benchmark
stepping frames itself -- has to call ``glutInit`` first.

Nor can it simply be called again for safety: freeglut answers a second
``glutInit`` with ``illegal glutInit() reinitialization attempt`` and exits too.
So it is asked once, and the asking is somewhere both paths reach.
"""
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import display_answers

pytest.importorskip('OpenGL.GLUT')

from OpenGLContext.testing.paths import tests_root
from OpenGLContext.windowsystem import glut as glutwindowsystem

DRIVER = tests_root(__file__) / 'helpers' / '_glut_init_drive.py'


def _drive(*steps):
    """Run the driver in a process of its own and answer what it reported

    A subprocess because the thing under test is whether the process survives:
    an ``exit()`` from inside freeglut would take the test runner with it.
    """
    result = subprocess.run(
        [sys.executable, str(DRIVER)] + list(steps),
        capture_output=True, text=True, timeout=180,
    )
    reported = {}
    for line in result.stdout.splitlines():
        head, _, tail = line.partition(' ')
        reported[head] = tail
    reported['_returncode'] = result.returncode
    reported['_stderr'] = result.stderr
    return reported


class TestTheInitialisationGuard:
    """The part that needs no display."""

    def test_it_says_whether_glut_has_been_initialised(self):

        assert callable(glutwindowsystem.glutInitialised)

    def test_asking_twice_initialises_once(self):
        """The whole reason for the guard: a second ``glutInit`` exits."""

        assert callable(glutwindowsystem.ensureGlutInitialised)


@pytest.mark.skipif(not display_answers(),
                    reason='GLUT needs an X display that answers; run under xvfb-run')
class TestAgainstARealDisplay:
    def test_a_context_can_be_built_directly(self):
        reported = _drive('build')
        assert reported.get('BUILT') == 'True', reported['_stderr'][-600:]
        assert reported['_returncode'] == 0

    def test_it_renders(self):
        reported = _drive('render')
        assert reported.get('PIXEL') == '64 128 192', reported['_stderr'][-600:]

    def test_several_contexts_in_one_process(self):
        """One per test is what a suite does, and freeglut has to survive it."""
        reported = _drive('several')
        assert reported.get('MADE') == '5', reported['_stderr'][-600:]
        assert reported['_returncode'] == 0

    def test_the_main_loop_path_still_initialises(self):
        """`ContextMainLoop` initialises GLUT before the context is built,
        and the constructor must not call ``glutInit`` a second time."""
        reported = _drive('mainloop')
        assert reported.get('LOOPED') == 'True', reported['_stderr'][-600:]
