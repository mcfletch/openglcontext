"""Declaring the context a test is about, and skipping where it is not to be had.

Most tests want *a* context and should take whatever this machine gives. A few
are about one kind of context and no other -- the compatibility profile's
fixed-function state, a particular windowing backend -- and those say so, run
where it can be had and skip where it cannot, rather than failing on a machine
that was never going to serve them.

See :mod:`OpenGLContext.testing.plugin`.
"""

import pytest

from OpenGLContext.testing import plugin


class TestWhatAMarkerAsksFor:
    def test_a_profile_and_a_backend_are_read_off_it(self):
        asked = plugin.context_asked_for(
            _marker(profile='compatibility', backend='glut'))
        assert asked == {'OPENGLCONTEXT_PROFILE': 'compatibility',
                         'OPENGLCONTEXT_BACKEND': 'glut'}

    def test_the_rest_of_the_configuration_comes_through_too(self):
        """A test about a context kind usually needs the options that go with
        it, and splitting them across a marker and an import would put half the
        answer where nothing can restore it."""
        asked = plugin.context_asked_for(_marker(profile='core', shadows=0))
        assert asked['OPENGLCONTEXT_SHADOWS'] == '0'
        assert asked['OPENGLCONTEXT_PROFILE'] == 'core'

    def test_a_name_already_spelled_in_full_is_left_as_it_is(self):
        asked = plugin.context_asked_for(
            _marker(OPENGLCONTEXT_INSTANCE_MIN=3))
        assert asked == {'OPENGLCONTEXT_INSTANCE_MIN': '3'}

    def test_nothing_asked_for_is_nothing_set(self):
        assert plugin.context_asked_for(_marker()) == {}


class TestWhenItIsPassedOver:
    def test_a_backend_whose_toolkit_is_absent_is_skipped(self):
        reason = plugin.context_skip_reason(
            {'OPENGLCONTEXT_BACKEND': 'nosuchtoolkit'},
            available=lambda name: False)
        assert reason and 'nosuchtoolkit' in reason

    def test_a_backend_that_is_there_runs(self):
        assert plugin.context_skip_reason(
            {'OPENGLCONTEXT_BACKEND': 'glfw'},
            available=lambda name: True) is None

    def test_a_profile_this_driver_will_not_give_is_skipped(self):
        reason = plugin.context_skip_reason(
            {'OPENGLCONTEXT_PROFILE': 'compatibility'},
            available=lambda name: True,
            profile_available=lambda profile: 'this driver is core-only')
        assert reason == 'this driver is core-only'

    def test_a_profile_it_will_give_runs(self):
        assert plugin.context_skip_reason(
            {'OPENGLCONTEXT_PROFILE': 'core'},
            available=lambda name: True,
            profile_available=lambda profile: None) is None

    def test_asking_for_no_kind_in_particular_asks_no_questions(self):
        """An unmarked test must not open a probe window to be told it did not
        need one."""
        def refuse(*args, **named):            # pragma: no cover - not called
            raise AssertionError('nothing should have been asked')
        assert plugin.context_skip_reason(
            {}, available=refuse, profile_available=refuse) is None


class _marker:
    """What :func:`context_asked_for` reads of a marker, and nothing else.

    ``pytest.Mark`` is private, and a test that reaches for it is testing
    pytest's internals as well as this.
    """

    def __init__(self, **named):
        self.kwargs = named
