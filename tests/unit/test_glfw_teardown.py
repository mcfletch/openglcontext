"""Whether a run hands its GLFW contexts back, and what decides that.

The stack under a run either frees a context cleanly or aborts the process
doing it (see :mod:`OpenGLContext.testing.glfwteardown`). Which one it is is a
question about the machine, so it is asked rather than assumed, and the answer
decides whether the engine's own release path runs or is stood down for the
session.

The decision is a plain function of the setting and the answer, so most of this
file needs no GL at all; the cases at the end ask this machine.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from OpenGLContext.testing import glcontext, glfwteardown


class FakeGLFW(SimpleNamespace):
    """Enough of the ``glfw`` module to be stood down."""

    def __init__(self) -> None:
        super().__init__()
        self.destroyed: list[object] = []
        self.terminated = 0

    def terminate(self) -> None:
        self.terminated += 1

    def destroy_window(self, window: object) -> None:
        self.destroyed.append(window)


@pytest.fixture(autouse=True)
def ask_again():
    """Every case decides for itself, rather than reading the answer the
    session's own settling left behind."""
    glfwteardown.forget()


### What the setting says
def test_nothing_set_means_ask_the_machine():
    assert glfwteardown.setting({}) == 'auto'


def test_an_empty_setting_means_the_same_as_none():
    """An unexported shell variable expands to the empty string."""
    assert glfwteardown.setting({glfwteardown.TEARDOWN_VARIABLE: ''}) == 'auto'


@pytest.mark.parametrize('written,expected', [
    ('native', 'native'),
    ('NATIVE', 'native'),
    (' neutralised ', 'neutralised'),
])
def test_a_setting_is_read_whatever_the_spacing_and_case(written, expected):
    assert glfwteardown.setting({glfwteardown.TEARDOWN_VARIABLE: written}) == expected


def test_a_setting_that_is_none_of_them_is_reported():
    """This variable is how a run pins the behaviour on a known stack, and a
    typo that quietly reversed the pin would make that run's result a lie."""
    with pytest.raises(ValueError) as caught:
        glfwteardown.setting({glfwteardown.TEARDOWN_VARIABLE: 'no-thanks'})
    assert glfwteardown.TEARDOWN_VARIABLE in str(caught.value)
    assert 'native' in str(caught.value)


### What it decides
def test_pinned_to_native_the_machine_is_not_asked():
    def refuse() -> bool:
        raise AssertionError('the probe ran for a setting that had decided')

    assert glfwteardown.teardown_choice('native', refuse) == 'native'


def test_pinned_to_neutralised_the_machine_is_not_asked_either():
    def refuse() -> bool:
        raise AssertionError('the probe ran for a setting that had decided')

    assert glfwteardown.teardown_choice('neutralised', refuse) == 'neutralised'


def test_a_stack_that_faults_is_stood_down():
    assert glfwteardown.teardown_choice('auto', lambda: True) == 'neutralised'


def test_a_stack_that_does_not_fault_keeps_its_own_teardown():
    """Which is what puts the engine's context-release path back under test as
    soon as the driver below it is fixed."""
    assert glfwteardown.teardown_choice('auto', lambda: False) == 'native'


### How long the probe has to be
def test_it_runs_enough_cycles_to_catch_an_intermittent_fault():
    """The fault is a fraction of teardowns, not every one.

    A probe of a few cycles answers "sound" on a faulting stack most of the
    time, and a run waved through that way crashes exactly as it would have
    without the probe. The cost is in starting the child and opening a window,
    not in the cycles, so there is nothing to trade against length.
    """
    missed = (1.0 - glfwteardown.FAULT_RATE) ** glfwteardown.CYCLES
    assert missed < 0.001, (
        '%d cycles miss a %.0f%%-of-teardowns fault %.1f%% of the time'
        % (glfwteardown.CYCLES, 100 * glfwteardown.FAULT_RATE, 100 * missed))


def test_the_rate_it_is_chosen_against_is_one_that_was_seen():
    """Recorded in PyOpenGL's `tests/README.md`: roughly one teardown in ten,
    on an NVIDIA driver, faulting inside `libnvidia-eglcore`."""
    assert 0.0 < glfwteardown.FAULT_RATE <= 0.1


### Reading the probe's result
@pytest.mark.parametrize('returncode,faults', [
    (0, False),                             # the child freed its contexts
    (glfwteardown.CANNOT_TELL, False),      # no GL here; nothing to protect
    (-6, True),                             # SIGABRT: the driver's bad free
    (-11, True),                            # SIGSEGV
    (1, True),                              # an exception on the way out
])
def test_what_each_way_the_probe_can_end_means(returncode, faults):
    assert glfwteardown.faults_from(returncode) is faults


def test_a_probe_that_cannot_be_launched_leaves_the_teardown_alone():
    """A machine that will not start a child process will not open a window on
    this backend either, so there is nothing for the workaround to protect."""
    def refuse(command):
        raise OSError('no')

    assert glfwteardown.teardown_faults(run=refuse) is False


def test_the_probe_is_asked_once_for_the_process():
    calls = []

    def count(command):
        calls.append(command)
        return 0

    glfwteardown.teardown_faults(run=count)
    glfwteardown.teardown_faults(run=count)
    assert len(calls) == 1


def test_the_probe_runs_this_interpreter():
    captured = []

    def capture(command):
        captured.append(command)
        return 0

    glfwteardown.teardown_faults(run=capture)
    assert captured[0][0] == sys.executable
    assert glfwteardown.__name__ in captured[0]


### Standing the teardown down
def test_neutralising_makes_both_calls_do_nothing():
    fake = FakeGLFW()
    glfwteardown.neutralise(fake)
    fake.destroy_window(object())
    fake.terminate()
    assert fake.destroyed == []
    assert fake.terminated == 0


def test_settling_on_a_sound_stack_changes_nothing():
    fake = FakeGLFW()
    assert glfwteardown.settle(fake, asked='native') == 'native'
    fake.destroy_window('a window')
    assert fake.destroyed == ['a window']


def test_settling_on_a_faulting_stack_stands_it_down():
    fake = FakeGLFW()
    assert glfwteardown.settle(fake, asked='neutralised') == 'neutralised'
    fake.destroy_window('a window')
    assert fake.destroyed == []


def test_settling_with_no_glfw_says_so():
    assert glfwteardown.settle(None, asked='neutralised') == 'unavailable'


### This machine
@pytest.fixture
def probe_result():
    """What the probe says about the stack this suite is running on."""
    if glcontext.windowing() != 'glfw':
        pytest.skip('this run does not make GLFW windows')
    if not glcontext.gl_available():
        pytest.skip('no GL context can be made here')
    return glfwteardown.teardown_faults()


def test_this_machine_gets_an_answer(probe_result):
    assert probe_result in (True, False)


def test_a_sound_stack_is_left_to_release_its_own_contexts(probe_result):
    """The engine's release path -- what a user's application runs on exit --
    is only under test where it is allowed to run, so the workaround has to go
    of its own accord rather than waiting to be noticed."""
    import glfw

    if glfwteardown.setting() != 'auto':
        pytest.skip('this run pins the teardown rather than asking')
    if probe_result:
        pytest.skip('this stack aborts on GLFW teardown; the workaround is in')
    assert glfw.destroy_window is not glfwteardown._NOTHING_TO_DO
    assert glfw.terminate is not glfwteardown._NOTHING_AT_ALL


def test_the_session_settled_this_the_same_way(probe_result):
    """The plugin decides once, before anything opens a window; this says the
    decision it recorded is the one this machine warrants."""
    from OpenGLContext.testing import plugin

    if glfwteardown.setting() != 'auto':
        pytest.skip('this run pins the teardown rather than asking')
    assert plugin.glfw_teardown() == (
        'neutralised' if probe_result else 'native')


def test_the_probe_itself_runs_here():
    """Run the child directly, so a probe that had stopped being able to build
    a window -- and so answered "faults" for the wrong reason -- is caught."""
    if glcontext.windowing() != 'glfw':
        pytest.skip('this run does not make GLFW windows')
    finished = subprocess.run(glfwteardown.probe_command(),
                              capture_output=True, timeout=120)
    assert finished.returncode in (0, glfwteardown.CANNOT_TELL, -6, -11), (
        finished.returncode, finished.stdout, finished.stderr)
