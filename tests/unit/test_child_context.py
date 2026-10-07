"""A test's child process that could not draw: a skip only where this machine has no context."""
import pytest

from OpenGLContext.testing import glcontext
from OpenGLContext.testing.plugin import NO_CONTEXT_STATUS, skip_if_child_had_no_context


@pytest.mark.parametrize('status', [0, 2])
def test_any_other_status_is_left_to_the_test(monkeypatch, status):
    asked = []
    monkeypatch.setattr(glcontext, 'profile_unavailable', asked.append)
    skip_if_child_had_no_context(status, 'assertion')
    assert asked == []


def test_no_context_where_this_machine_has_none_is_a_skip(monkeypatch):
    monkeypatch.setattr(glcontext, 'profile_unavailable', lambda profile: 'no %s here' % profile)
    with pytest.raises(pytest.skip.Exception, match='no core here'):
        skip_if_child_had_no_context(NO_CONTEXT_STATUS, 'NOGL ...')


def test_no_context_where_this_machine_has_one_is_a_failure(monkeypatch):
    monkeypatch.setattr(glcontext, 'profile_unavailable', lambda profile: None)
    with pytest.raises(pytest.fail.Exception, match='AttributeError'):
        skip_if_child_had_no_context(NO_CONTEXT_STATUS, "NOGL AttributeError('unlit')")


def test_the_profile_asked_about_is_the_one_named(monkeypatch):
    asked = []
    monkeypatch.setattr(glcontext, 'profile_unavailable',
                        lambda profile: asked.append(profile) or 'refused')
    with pytest.raises(pytest.skip.Exception):
        skip_if_child_had_no_context(NO_CONTEXT_STATUS, '', profile='compatibility')
    assert asked == ['compatibility']
