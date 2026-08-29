"""A node that fails to render is named, once, and again at the end of the run.

The render passes catch every per-node exception so one bad node cannot kill the
frame.  That is right, and it is also how a scene can draw nothing at all while
the process exits 0: the traceback goes to a log at a level nobody is watching,
once per node per frame, and the frame is black.

:class:`RenderFailureLog` is the part of that with no GL in it -- what counts as
the same failure, what gets logged and what gets held for the summary -- so it is
tested here directly rather than through a window.
"""

import logging

import pytest

from OpenGLContext.passes.renderfailures import RenderFailureLog, describe


class _Node:
    """Stands in for a scenegraph node: the log wants only its type and name."""

    def __init__(self, name='node'):
        self.DEF = name


@pytest.fixture
def failures():
    return RenderFailureLog()


class TestOneFailureIsLoudAndTheRestAreCounted:
    def test_the_first_failure_of_a_kind_asks_to_be_logged(self, failures):
        assert failures.record('opaque', _Node(), ValueError('nope')) is True

    def test_the_same_failure_again_does_not(self, failures):
        failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.record('opaque', _Node(), ValueError('nope')) is False

    def test_every_occurrence_is_counted(self, failures):
        for _ in range(5):
            failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.summary()[0].count == 5

    def test_a_different_exception_is_a_different_failure(self, failures):
        failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.record('opaque', _Node(), TypeError('other')) is True

    def test_a_different_message_is_a_different_failure(self, failures):
        failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.record('opaque', _Node(), ValueError('worse')) is True

    def test_a_different_pass_is_a_different_failure(self, failures):
        failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.record('transparent', _Node(), ValueError('nope')) is True

    def test_a_different_node_type_is_a_different_failure(self, failures):
        class _Other(_Node):
            pass

        failures.record('opaque', _Node(), ValueError('nope'))
        assert failures.record('opaque', _Other(), ValueError('nope')) is True

    def test_only_the_first_line_of_a_message_distinguishes_it(self, failures):
        """A GLError prints its whole call over several lines; the first names it."""
        failures.record('opaque', _Node(), ValueError('invalid operation\n  at x'))
        assert failures.record(
            'opaque', _Node(), ValueError('invalid operation\n  at y')) is False


class TestWhatTheSummarySays:
    def test_nothing_failed_means_nothing_to_say(self, failures):
        assert failures.summary() == []

    def test_the_summary_names_the_node_and_the_pass(self, failures):
        failures.record('opaque', _Node('Ground'), ValueError('nope'))
        entry = failures.summary()[0]
        assert entry.where == 'opaque'
        assert '_Node' in entry.description
        assert 'nope' in entry.description

    def test_the_worst_offender_comes_first(self, failures):
        for _ in range(3):
            failures.record('opaque', _Node(), ValueError('common'))
        failures.record('opaque', _Node(), ValueError('rare'))
        assert [entry.count for entry in failures.summary()] == [3, 1]

    def test_reporting_says_how_many_and_how_often(self, failures, caplog):
        for _ in range(4):
            failures.record('opaque', _Node(), ValueError('nope'))
        with caplog.at_level(logging.WARNING):
            failures.report()
        assert 'nope' in caplog.text
        assert '4' in caplog.text

    def test_reporting_nothing_logs_nothing(self, failures, caplog):
        with caplog.at_level(logging.DEBUG):
            failures.report()
        assert caplog.text == ''

    def test_a_report_can_be_asked_for_twice_without_repeating_itself(
            self, failures, caplog):
        """Teardown may run more than once; the run gets one account of itself."""
        failures.record('opaque', _Node(), ValueError('nope'))
        failures.report()
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            failures.report()
        assert caplog.text == ''


class TestTheNodesCannotBreakTheLog:
    def test_a_node_whose_name_raises_is_still_recorded(self, failures):
        class _Hostile:
            @property
            def DEF(self):
                raise RuntimeError('no name for you')

        assert failures.record('opaque', _Hostile(), ValueError('nope')) is True
        assert failures.summary()[0].count == 1

    def test_a_node_that_is_none_is_still_recorded(self, failures):
        assert failures.record('opaque', None, ValueError('nope')) is True

    def test_an_exception_whose_str_raises_is_still_recorded(self, failures):
        class _Hostile(Exception):
            def __str__(self):
                raise RuntimeError('no message for you')

        assert failures.record('opaque', _Node(), _Hostile()) is True


class TestHowAFailureIsExplained:
    """What the first occurrence of a cause carries into the log."""

    def test_a_raised_error_is_explained_by_its_traceback(self):
        try:
            raise RuntimeError('the geometry cannot draw')
        except RuntimeError as err:
            explanation = describe(err)
        assert 'Traceback' in explanation
        assert 'the geometry cannot draw' in explanation

    def test_an_error_that_was_never_raised_is_explained_by_its_message(self):
        """A failure the pass worked out for itself has no stack to show."""
        assert describe(RuntimeError('no normals')) == 'RuntimeError: no normals'

    def test_an_unraised_error_is_not_lent_someone_elses_traceback(self):
        try:
            raise ValueError('a different failure entirely')
        except ValueError:
            explanation = describe(RuntimeError('no normals'))
        assert 'a different failure entirely' not in explanation
