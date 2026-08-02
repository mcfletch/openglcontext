"""The suite renders offscreen unless somebody asks to watch it.

Several hundred of these tests open a GL context. Mapped, that is several
hundred windows opening, flashing over whatever the person running the suite is
doing, and taking the keyboard focus while they type. A hidden window renders
and reads back identically, so there is nothing to trade away.

It is also the only arrangement in which a buffer swap is guaranteed not to
block: a compositor throttles the swap to its own frame callback, and a window
nothing is drawing to the screen never gets one.
"""
import os
import subprocess
import sys

import pytest


def test_the_run_is_offscreen_by_default():
    """Set in ``tests/conftest.py``, so it holds for the whole session."""
    assert os.environ.get('OPENGLCONTEXT_HIDDEN') == '1'


def test_swaps_do_not_wait_for_a_compositor():
    assert os.environ.get('OPENGLCONTEXT_NO_VSYNC') == '1'


def test_a_subprocess_test_inherits_it():
    """Most GL tests run in a subprocess; those windows are the loud ones."""
    result = subprocess.run(
        [sys.executable, '-c',
         'import os; print(os.environ.get("OPENGLCONTEXT_HIDDEN"))'],
        capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == '1'


def test_the_runner_passes_it_through_its_own_overrides():
    """It merges over ``os.environ`` rather than replacing it."""
    from OpenGLContext.testing import subprocess_runner
    import inspect
    source = inspect.getsource(subprocess_runner.run_test_with_popen)
    assert '{**os.environ,' in source, 'a clean env would drop the default'


def test_it_can_be_turned_off_to_watch_something(monkeypatch):
    """Watching a test render is how you find out why it looks wrong.

    ``setdefault`` rather than an assignment, so an explicit setting in the
    environment survives.
    """
    from OpenGLContext import renderoptions
    monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '0')
    assert not renderoptions.env_flag('OPENGLCONTEXT_HIDDEN', True)


@pytest.mark.parametrize('name', ['OPENGLCONTEXT_HIDDEN', 'OPENGLCONTEXT_NO_VSYNC'])
def test_the_switch_is_one_the_renderer_knows_about(name):
    """A variable nothing reads would be a setting that quietly does nothing."""
    from OpenGLContext import renderoptions
    assert name in renderoptions.ENVIRONMENT
