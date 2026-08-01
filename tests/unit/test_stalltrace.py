"""The trace written to disk while the loop is slow, and the report read back.

The phase breakdown says *which subsystem* owned a slow frame. It cannot say
which code inside that subsystem, and by the time the iteration closes the
stack that would have said is already unwound. So a watcher thread samples the
main thread's stack **while an iteration is overrunning**, and consecutive slow
iterations are gathered into one *episode* -- because "the game went unplayable
for four seconds" is one thing that happened, not two hundred.

These pin the sampling, the episode grouping, the file the two produce, and the
report that reads it back.
"""

import json
import logging
import sys
import threading
import time

import pytest

from OpenGLContext.stalltrace import (
    StackSampler, StallJournal, describe_episode, hot_functions, hot_stacks,
    install, read_episodes, stack_of,
)


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


# -- what a stack looks like ------------------------------------------------

def _inner_function():
    return sys._getframe()


def _outer_function():
    return _inner_function()


class TestStackOf:
    def test_the_innermost_call_comes_first(self):
        found = stack_of(_outer_function())
        assert found[0][2] == '_inner_function'
        assert found[1][2] == '_outer_function'

    def test_each_level_is_file_line_and_function(self):
        filename, line, function = stack_of(_outer_function())[0]
        assert filename.endswith('test_stalltrace.py')
        assert isinstance(line, int) and line > 0
        assert function == '_inner_function'

    def test_a_deep_stack_is_cut_rather_than_kept_whole(self):
        """A runaway recursion must not put ten thousand frames in a record."""
        def recurse(depth):
            if depth:
                return recurse(depth - 1)
            return sys._getframe()

        found = stack_of(recurse(200), depth=12)
        assert len(found) == 12

    def test_no_frame_is_an_empty_stack_rather_than_a_failure(self):
        assert stack_of(None) == ()


# -- aggregating them -------------------------------------------------------

ALPHA = (('a.py', 1, 'step'), ('b.py', 2, 'main'))
BETA = (('c.py', 3, 'draw'), ('b.py', 2, 'main'))


class TestHotStacks:
    def test_the_most_sampled_stack_comes_first(self):
        found = hot_stacks([ALPHA, BETA, ALPHA, ALPHA])
        assert found[0]['count'] == 3
        assert found[0]['stack'][0] == 'a.py:1 step'
        assert found[1]['count'] == 1

    def test_each_carries_its_share_of_the_samples(self):
        found = hot_stacks([ALPHA, ALPHA, ALPHA, BETA])
        assert found[0]['percent'] == pytest.approx(75.0)

    def test_only_the_worst_few_are_kept(self):
        stacks = [(('%d.py' % index, 1, 'f'),) for index in range(20)]
        assert len(hot_stacks(stacks, keep=3)) == 3

    def test_nothing_sampled_is_nothing_reported(self):
        assert hot_stacks([]) == []


# -- taking the samples -----------------------------------------------------

class TestHotFunctions:
    """The tally that survives a function being reached a dozen ways.

    Grouping by the whole stack splits one expensive function across every call
    site and every line that reaches it, so a function taking 60% of a stall
    reads as a dozen entries at 5% and the file looks like it found nothing.
    A per-function tally is what says outright where the time went.
    """

    # The same leaf, reached from three different lines of the same caller --
    # which is what a real sampled stall looks like.
    ROUTES = [
        (('collide.py', 379, 'closest_point'), ('char.py', 524, 'step')),
        (('collide.py', 379, 'closest_point'), ('char.py', 569, 'step')),
        (('collide.py', 371, 'closest_point'), ('char.py', 571, 'step')),
        (('render.py', 12, 'draw'), ('main.py', 3, 'loop')),
    ]

    def test_one_function_reached_many_ways_is_tallied_once(self):
        found = {entry['name']: entry for entry in hot_functions(self.ROUTES)}
        assert found['collide.py closest_point']['self_percent'] \
            == pytest.approx(75.0)

    def test_line_numbers_do_not_split_a_function(self):
        """Lines 379 and 371 are the same function having a bad time."""
        names = [entry['name'] for entry in hot_functions(self.ROUTES)]
        assert names.count('collide.py closest_point') == 1

    def test_self_says_where_the_samples_actually_were(self):
        found = {entry['name']: entry for entry in hot_functions(self.ROUTES)}
        assert found['char.py step']['self_percent'] == 0.0

    def test_cumulative_says_what_the_cost_was_inside_of(self):
        """`step` never holds a sample itself, and owns three quarters of them."""
        found = {entry['name']: entry for entry in hot_functions(self.ROUTES)}
        assert found['char.py step']['cumulative_percent'] == pytest.approx(75.0)

    def test_a_function_recursing_is_still_one_sample_of_cumulative(self):
        recursive = [(('a.py', 1, 'f'), ('a.py', 2, 'f'), ('a.py', 3, 'f'))]
        found = hot_functions(recursive)
        assert found[0]['cumulative_percent'] == pytest.approx(100.0)

    def test_the_worst_comes_first(self):
        ordered = [entry['name'] for entry in hot_functions(self.ROUTES)]
        assert ordered[0] == 'collide.py closest_point'

    def test_only_the_worst_few_are_kept(self):
        stacks = [(('%d.py' % index, 1, 'f'),) for index in range(30)]
        assert len(hot_functions(stacks, keep=4)) == 4

    def test_nothing_sampled_is_nothing_reported(self):
        assert hot_functions([]) == []

    def test_an_empty_stack_is_skipped_rather_than_counted(self):
        assert hot_functions([(), (('a.py', 1, 'f'),)])[0]['self_percent'] \
            == pytest.approx(100.0)


class TestStackSampler:
    def test_it_only_samples_when_the_predicate_says_to(self, clock):
        """A healthy loop must not be profiled: the overhead is the subject."""
        sampling = [False]
        sampler = StackSampler(when=lambda: sampling[0], clock=clock)
        sampler.sample()
        assert sampler.count == 0
        sampling[0] = True
        sampler.sample()
        assert sampler.count == 1

    def test_samples_are_stamped_so_an_episode_can_claim_its_own(self, clock):
        sampler = StackSampler(when=lambda: True, clock=clock)
        clock.advance(5.0)
        sampler.sample()
        clock.advance(1.0)
        sampler.sample()
        assert [stamp for stamp, _stack in sampler.between(0.0, 10.0)] == [5.0, 6.0]

    def test_an_episode_takes_only_the_samples_inside_it(self, clock):
        sampler = StackSampler(when=lambda: True, clock=clock)
        for _ in range(5):
            sampler.sample()
            clock.advance(1.0)
        assert len(sampler.between(1.0, 3.0)) == 3

    def test_the_buffer_is_bounded(self, clock):
        sampler = StackSampler(when=lambda: True, keep=10, clock=clock)
        for _ in range(100):
            sampler.sample()
            clock.advance(0.001)
        assert sampler.held == 10

    def test_it_says_when_it_dropped_the_start_of_an_episode(self, clock):
        """A silent truncation reads as 'this is all that happened'."""
        sampler = StackSampler(when=lambda: True, keep=5, clock=clock)
        for _ in range(50):
            sampler.sample()
            clock.advance(1.0)
        assert sampler.complete_since(0.0) is False
        assert sampler.complete_since(clock.now - 2.0) is True

    def test_a_sampler_with_nothing_held_is_complete_about_nothing(self, clock):
        assert StackSampler(when=lambda: True, clock=clock).complete_since(0.0)

    def test_it_samples_the_thread_it_was_told_to(self, clock):
        sampler = StackSampler(when=lambda: True, clock=clock,
                               thread_id=threading.current_thread().ident)
        sampler.sample()
        functions = [level[2] for level in sampler.between(-1.0, 1.0)[0][1]]
        assert 'test_it_samples_the_thread_it_was_told_to' in functions

    def test_a_thread_that_has_gone_is_not_an_error(self, clock):
        sampler = StackSampler(when=lambda: True, clock=clock,
                               thread_id=-1)          # no such thread
        sampler.sample()
        assert sampler.count == 0


class TestTheSamplerThread:
    """The real thing, against a real thread doing real work."""

    def test_it_catches_the_function_that_is_running(self):
        overrunning = [False]
        sampler = StackSampler(when=lambda: overrunning[0], interval=0.002,
                               thread_id=threading.current_thread().ident)
        sampler.start()
        try:
            def the_slow_function():
                deadline = time.perf_counter() + 0.25
                total = 0
                while time.perf_counter() < deadline:
                    total += 1
                return total

            time.sleep(0.02)                    # healthy: nothing sampled
            assert sampler.count == 0
            overrunning[0] = True
            the_slow_function()
            overrunning[0] = False
        finally:
            sampler.stop()
        assert sampler.count > 10
        functions = {level[2]
                     for _stamp, stack in sampler.between(0.0, float('inf'))
                     for level in stack}
        assert 'the_slow_function' in functions

    def test_stopping_is_idempotent_and_starting_twice_is_one_thread(self):
        sampler = StackSampler(when=lambda: False)
        sampler.start()
        sampler.start()
        sampler.stop()
        sampler.stop()
        assert sampler.count == 0


# -- gathering them into episodes -------------------------------------------

class StubSampler:
    """A sampler whose samples the test states outright."""

    def __init__(self, stacks=(), complete=True):
        self.stacks = list(stacks)
        self._complete = complete
        self.count = len(self.stacks)

    def between(self, start, end):
        return [(start, stack) for stack in self.stacks]

    def complete_since(self, when):
        return self._complete


def _journal(tmp_path, clock, **named):
    named.setdefault('sampler', StubSampler([ALPHA]))
    return StallJournal(tmp_path / 'stalls.jsonl', clock=clock,
                        now=lambda: 1700000000.0, **named)


def _run(journal, clock, iterations):
    """Feed ``[(seconds, stalled), ...]`` through as loop iterations."""
    for seconds, stalled in iterations:
        clock.advance(seconds)
        journal(seconds, {'match': seconds * 0.8, 'render': seconds * 0.2},
                stalled)


class TestEpisodes:
    def test_a_healthy_loop_writes_nothing_at_all(self, tmp_path, clock):
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.016, False)] * 50)
        journal.close()
        assert read_episodes(journal.path) == []

    def test_consecutive_slow_iterations_are_one_episode(self, tmp_path, clock):
        """Four unplayable seconds are one thing that happened, not two hundred."""
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.016, False)] * 5 + [(0.200, True)] * 20
             + [(0.016, False)] * 10)
        journal.close()
        found = read_episodes(journal.path)
        assert len(found) == 1
        assert found[0]['stalled'] == 20
        assert found[0]['seconds'] == pytest.approx(4.0, abs=0.1)

    def test_two_slow_periods_far_apart_are_two_episodes(self, tmp_path, clock):
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 3 + [(0.016, False)] * 20
             + [(0.200, True)] * 3)
        journal.close()
        assert len(read_episodes(journal.path)) == 2

    def test_one_good_frame_does_not_end_a_slow_period(self, tmp_path, clock):
        journal = _journal(tmp_path, clock, gap=4)
        _run(journal, clock, [(0.200, True)] * 3 + [(0.016, False)]
             + [(0.200, True)] * 3)
        journal.close()
        found = read_episodes(journal.path)
        assert len(found) == 1
        assert found[0]['stalled'] == 6

    def test_an_episode_still_open_at_shutdown_is_written(self, tmp_path, clock):
        """A run killed mid-stall is exactly the run worth having a record of."""
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 5)
        journal.close()
        assert read_episodes(journal.path)[0]['stalled'] == 5

    def test_closing_twice_does_not_write_it_twice(self, tmp_path, clock):
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 3)
        journal.close()
        journal.close()
        assert len(read_episodes(journal.path)) == 1


class TestALongSlowPeriodIsNotHeldHostage:
    """A stall at the *end* of a session is the one an unflushed record loses.

    An episode is written when it closes, so a slow period still open when the
    process dies is a slow period nobody ever sees -- and a session that ends
    while it is struggling is the commonest way to end one. So an episode is
    also cut and written once it has run long enough, and the next part
    continues it.
    """

    def test_a_long_slow_period_is_written_in_parts_as_it_happens(
            self, tmp_path, clock):
        journal = _journal(tmp_path, clock, max_seconds=2.0)
        _run(journal, clock, [(0.200, True)] * 50)      # ten seconds of stall
        assert len(read_episodes(journal.path)) >= 4    # before any close()
        journal.close()

    def test_a_continuation_says_that_it_is_one(self, tmp_path, clock):
        journal = _journal(tmp_path, clock, max_seconds=2.0)
        _run(journal, clock, [(0.200, True)] * 30)
        journal.close()
        found = read_episodes(journal.path)
        assert found[0]['continues'] is False
        assert found[1]['continues'] is True

    def test_a_short_slow_period_is_still_one_episode(self, tmp_path, clock):
        journal = _journal(tmp_path, clock, max_seconds=10.0)
        _run(journal, clock, [(0.200, True)] * 5)
        journal.close()
        assert len(read_episodes(journal.path)) == 1

    def test_the_parts_together_account_for_the_whole_slow_period(
            self, tmp_path, clock):
        journal = _journal(tmp_path, clock, max_seconds=2.0)
        _run(journal, clock, [(0.200, True)] * 50)
        journal.close()
        found = read_episodes(journal.path)
        assert sum(part['stalled'] for part in found) == 50


class TestWhatAnEpisodeSays:
    @pytest.fixture
    def episode(self, tmp_path, clock):
        journal = _journal(
            tmp_path, clock,
            sampler=StubSampler([ALPHA, ALPHA, ALPHA, BETA]),
            context=lambda: {'Map': {'name': 'ztn3dm1'}, 'Combat': {'bots': 4}})
        _run(journal, clock, [(0.016, False)] * 20)
        _run(journal, clock, [(0.100, True), (0.800, True), (0.100, True)])
        journal.close()
        return read_episodes(journal.path)[0]

    def test_it_says_when_and_how_long(self, episode):
        # ISO-8601 UTC off the *wall* clock, so an episode can be lined up
        # against anything else's log; the monotonic clock measures the length.
        assert episode['at'] == '2023-11-14T22:13:20+00:00'
        assert episode['seconds'] == pytest.approx(1.0, abs=0.05)

    def test_it_says_how_bad_the_worst_iteration_was(self, episode):
        assert episode['worst_ms'] == pytest.approx(800.0)
        assert episode['mean_ms'] == pytest.approx(1000.0 / 3, abs=1.0)

    def test_it_says_what_the_loop_was_doing_before_it_went_wrong(self, episode):
        """Without the baseline, 'slow' has nothing to be slow compared to."""
        assert episode['baseline_ms'] == pytest.approx(16.0, abs=1.0)

    def test_it_divides_the_time_among_the_phases(self, episode):
        assert episode['phases_ms']['match'] > episode['phases_ms']['render']

    def test_it_names_the_code_that_was_running(self, episode):
        """The whole point: which function, not merely which subsystem."""
        assert episode['hot'][0]['stack'][0] == 'a.py:1 step'
        assert episode['hot'][0]['percent'] == pytest.approx(75.0)

    def test_it_carries_whatever_the_application_wanted_recorded(self, episode):
        assert episode['context']['Map']['name'] == 'ztn3dm1'
        assert episode['context']['Combat']['bots'] == 4

    def test_it_admits_when_its_samples_are_incomplete(self, tmp_path, clock):
        journal = _journal(tmp_path, clock,
                           sampler=StubSampler([ALPHA], complete=False))
        _run(journal, clock, [(0.500, True)] * 3)
        journal.close()
        assert read_episodes(journal.path)[0]['samples']['incomplete'] is True


class TestTheFileItself:
    def test_it_opens_with_a_header_naming_the_run(self, tmp_path, clock):
        journal = _journal(tmp_path, clock, stall_ms=40.0)
        journal.close()
        first = json.loads(journal.path.read_text().splitlines()[0])
        assert first['kind'] == 'header'
        assert first['stall_ms'] == 40.0
        assert 'started' in first and 'argv' in first

    def test_each_episode_is_one_line_of_json(self, tmp_path, clock):
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 2 + [(0.016, False)] * 20
             + [(0.200, True)] * 2)
        journal.close()
        lines = journal.path.read_text().splitlines()
        assert len(lines) == 3                        # header + two episodes
        assert all(json.loads(line) for line in lines)

    def test_an_episode_is_flushed_as_it_happens(self, tmp_path, clock):
        """A run that ends in a kill -9 must still have its earlier episodes."""
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 2 + [(0.016, False)] * 20)
        assert len(read_episodes(journal.path)) == 1  # before any close()
        journal.close()

    def test_a_directory_that_does_not_exist_yet_is_made(self, tmp_path, clock):
        journal = StallJournal(tmp_path / 'deep' / 'down' / 'stalls.jsonl',
                               clock=clock, sampler=StubSampler([ALPHA]))
        journal.close()
        assert journal.path.exists()

    def test_a_path_that_cannot_be_written_is_a_warning_not_a_crash(
            self, tmp_path, clock, caplog):
        """A diagnostic must never be the reason a game will not start."""
        blocked = tmp_path / 'a-file'
        blocked.write_text('not a directory')
        with caplog.at_level(logging.WARNING, logger='OpenGLContext.stalltrace'):
            journal = StallJournal(blocked / 'stalls.jsonl', clock=clock,
                                   sampler=StubSampler([ALPHA]))
            _run(journal, clock, [(0.200, True)] * 3)
            journal.close()
        assert 'stalls.jsonl' in caplog.text
        assert journal.disabled is True


class TestReadingItBack:
    def test_a_report_names_the_worst_episode_and_its_hottest_stack(
            self, tmp_path, clock):
        journal = _journal(tmp_path, clock,
                           sampler=StubSampler([ALPHA, ALPHA, BETA]))
        _run(journal, clock, [(0.016, False)] * 20)
        _run(journal, clock, [(0.900, True)] * 3)
        journal.close()
        printed = describe_episode(read_episodes(journal.path)[0])
        assert '900' in printed
        assert 'a.py:1 step' in printed
        assert 'match' in printed

    def test_a_file_with_no_episodes_reads_as_an_empty_list(self, tmp_path, clock):
        journal = _journal(tmp_path, clock)
        journal.close()
        assert read_episodes(journal.path) == []

    def test_a_truncated_last_line_does_not_lose_the_rest(self, tmp_path, clock):
        """A run killed mid-write still has every episode before the last."""
        journal = _journal(tmp_path, clock)
        _run(journal, clock, [(0.200, True)] * 2 + [(0.016, False)] * 20)
        journal.close()
        with open(journal.path, 'a') as handle:
            handle.write('{"kind": "episode", "seco')
        assert len(read_episodes(journal.path)) == 1


class TestInstalling:
    def test_nothing_is_installed_without_the_variable(self, monkeypatch):
        from OpenGLContext.looptrace import LoopTrace

        monkeypatch.delenv('OPENGLCONTEXT_STALL_TRACE', raising=False)
        assert install(LoopTrace()) is None

    def test_the_variable_names_the_file(self, monkeypatch, tmp_path):
        from OpenGLContext.looptrace import LoopTrace

        target = tmp_path / 'run.jsonl'
        monkeypatch.setenv('OPENGLCONTEXT_STALL_TRACE', str(target))
        trace = LoopTrace(stall_ms=20.0)
        journal = install(trace)
        try:
            assert journal is not None
            assert journal.path == target
            assert target.exists()
        finally:
            journal.close()

    def test_the_journal_hears_the_trace_it_was_installed_on(
            self, monkeypatch, tmp_path):
        from OpenGLContext.looptrace import LoopTrace

        monkeypatch.setenv('OPENGLCONTEXT_STALL_TRACE',
                           str(tmp_path / 'run.jsonl'))
        clock = FakeClock()
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        journal = install(trace)
        try:
            with trace.iteration():
                clock.advance(0.500)
        finally:
            journal.close()
        assert read_episodes(journal.path)[0]['stalled'] == 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
