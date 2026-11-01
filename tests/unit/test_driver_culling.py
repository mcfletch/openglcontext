"""Back faces with a vertex at clip w = 0 culled, and the driver switch that keeps them culled.

On an affected radeonsi stack the vertex-stage culling draws a back face
that has a vertex on the plane through the eye
(see :mod:`OpenGLContext.testing.drivercull`). The decision to switch the
driver's vertex-stage culling off is a plain function of the setting and the
machine, so most of this file needs no GL; the cases at the end draw.
"""

from __future__ import annotations

import os
import sys

import pytest

from OpenGLContext.testing import drivercull, glcontext, plugin


@pytest.fixture(autouse=True)
def ask_again():
    """Every case decides for itself, rather than reading the session's answer."""
    drivercull.forget()
    yield
    drivercull.forget()


### What the setting says
def test_nothing_set_means_ask_the_machine():
    assert drivercull.setting({}) == 'auto'


def test_an_empty_setting_means_the_same_as_none():
    assert drivercull.setting({drivercull.CULLING_VARIABLE: ''}) == 'auto'


@pytest.mark.parametrize('written,expected', [('on', 'on'), (' OFF ', 'off'), ('Auto', 'auto')])
def test_a_setting_is_read_whatever_the_spacing_and_case(written, expected):
    assert drivercull.setting({drivercull.CULLING_VARIABLE: written}) == expected


def test_a_setting_that_is_none_of_them_is_reported():
    with pytest.raises(ValueError, match=drivercull.CULLING_VARIABLE):
        drivercull.setting({drivercull.CULLING_VARIABLE: 'of'})


### What decides
def asked_and_misculls():
    raise AssertionError('a pinned setting asks nothing of the machine')


@pytest.mark.parametrize('pinned', ['on', 'off'])
def test_a_pinned_setting_does_not_ask_the_machine(pinned):
    assert drivercull.culling_choice(pinned, asked_and_misculls) == pinned


def test_a_driver_that_misculls_has_its_culling_switched_off():
    assert drivercull.culling_choice('auto', lambda: True) == 'off'


def test_a_driver_that_culls_keeps_its_culling():
    assert drivercull.culling_choice('auto', lambda: False) == 'on'


@pytest.mark.parametrize('returncode,misculls', [
    (0, False),
    (drivercull.MISCULLS, True),
    (drivercull.CANNOT_TELL, False),
    (-11, False),
])
def test_what_each_way_the_probe_can_end_means(returncode, misculls):
    assert drivercull.misculls_from(returncode) is misculls


def test_a_probe_that_cannot_be_launched_leaves_the_driver_alone():
    def refuses(command):
        raise OSError('no child processes here')
    assert drivercull.driver_misculls(refuses) is False


def test_the_probe_is_asked_once_for_the_process():
    calls = []

    def run(command):
        calls.append(command)
        return drivercull.MISCULLS
    assert drivercull.driver_misculls(run) is True
    assert drivercull.driver_misculls(run) is True
    assert len(calls) == 1


def test_the_probe_runs_this_interpreter():
    command = drivercull.probe_command()
    assert command[0] == sys.executable
    assert command[1:] == ('-m', 'OpenGLContext.testing.drivercull')


### What settling does to the environment
@pytest.mark.parametrize('before,after', [
    (None, 'nonggc'),
    ('', 'nonggc'),
    ('nodcc', 'nodcc,nonggc'),
    ('nonggc', 'nonggc'),
    (' nodcc , nonggc ', 'nodcc,nonggc'),
])
def test_the_flag_joins_whatever_amd_debug_already_says(before, after):
    assert drivercull.with_flag(before) == after


def test_switching_it_off_adds_the_flag_and_pins_the_answer_for_children():
    environ = {'AMD_DEBUG': 'nodcc'}
    assert drivercull.settle(environ, lambda: True) == 'off'
    assert environ == {'AMD_DEBUG': 'nodcc,nonggc', drivercull.CULLING_VARIABLE: 'off'}


def test_leaving_it_on_changes_nothing_but_the_pin():
    environ = {'AMD_DEBUG': 'nodcc'}
    assert drivercull.settle(environ, lambda: False) == 'on'
    assert environ == {'AMD_DEBUG': 'nodcc', drivercull.CULLING_VARIABLE: 'on'}


def test_a_pinned_answer_is_not_asked_again():
    environ = {drivercull.CULLING_VARIABLE: 'off'}
    assert drivercull.settle(environ, asked_and_misculls) == 'off'
    assert environ['AMD_DEBUG'] == 'nonggc'


### This machine
@pytest.fixture
def glfw_run():
    if glcontext.windowing() != 'glfw':
        pytest.skip('this run does not make GLFW windows')


def test_the_session_settled_before_its_first_window(glfw_run):
    assert plugin.ngg_culling() in ('on', 'off')
    assert os.environ[drivercull.CULLING_VARIABLE] == plugin.ngg_culling()
    switched_off = drivercull.NO_NGG_CULLING in os.environ.get('AMD_DEBUG', '').split(',')
    assert switched_off == (plugin.ngg_culling() == 'off')


def test_a_solid_shape_in_a_second_window_culls_its_back_faces(glfw_run):
    """Seen from inside, a solid Cone's faces are all back faces, so the frame is black

    Its apex and base centre are at clip w = 0, which the affected driver
    leaves unculled.
    """
    green, _renderer = drivercull.second_window_green()
    assert green < 40
