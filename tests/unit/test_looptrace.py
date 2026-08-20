"""Wall-clock timing of the main loop, which is the number the frame rate is not.

The frame counter times the inside of ``OnDraw``; a backend's loop also polls
events, runs ``OnIdle`` and waits, and a game whose whole update lives in
``OnIdle`` can crawl while the counter goes on reporting a healthy rate.  These
tests pin the difference, and pin the two things a median deliberately throws
away: the worst iteration in the window, and how many of them crossed a stall
threshold.
"""

import logging

import pytest

from OpenGLContext.looptrace import LoopTrace, describe_phases


class FakeClock:
    """A clock the test advances by hand, so timings are exact, not flaky."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def _iterate(trace, clock, phases):
    """Run one iteration spending ``phases`` -- [(name, seconds), ...]."""
    with trace.iteration():
        for name, seconds in phases:
            with trace.phase(name):
                clock.advance(seconds)


class TestIterationTiming:
    def test_an_iteration_records_its_wall_time(self, clock):
        trace = LoopTrace(clock=clock)
        _iterate(trace, clock, [('idle', 0.020)])
        assert trace.summary()['median_ms'] == pytest.approx(20.0)

    def test_the_rate_is_iterations_per_second_of_wall_clock(self, clock):
        trace = LoopTrace(clock=clock)
        for _ in range(10):
            _iterate(trace, clock, [('idle', 0.050)])
        assert trace.summary()['rate'] == pytest.approx(20.0)

    def test_nothing_measured_yet_reports_zeroes_rather_than_failing(self):
        summary = LoopTrace().summary()
        assert summary['iterations'] == 0
        assert summary['rate'] == 0.0
        assert summary['median_ms'] == 0.0

    def test_the_window_is_bounded(self, clock):
        trace = LoopTrace(window=8, clock=clock)
        for _ in range(100):
            _iterate(trace, clock, [('idle', 0.001)])
        assert trace.summary()['iterations'] == 8


class TestWhatTheMedianHides:
    """The reason this module exists: a median cannot report a hitch."""

    def test_the_worst_iteration_survives_a_median_that_looks_healthy(self, clock):
        trace = LoopTrace(clock=clock)
        for _ in range(30):
            _iterate(trace, clock, [('draw', 0.020)])
        _iterate(trace, clock, [('idle', 1.000)])      # one second lost
        for _ in range(30):
            _iterate(trace, clock, [('draw', 0.020)])

        summary = trace.summary()
        assert summary['median_ms'] == pytest.approx(20.0)   # median: all well
        assert summary['worst_ms'] == pytest.approx(1000.0)  # worst: not at all

    def test_iterations_over_the_threshold_are_counted(self, clock):
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        for _ in range(5):
            _iterate(trace, clock, [('draw', 0.020)])
        for _ in range(3):
            _iterate(trace, clock, [('idle', 0.500)])
        assert trace.summary()['stalls'] == 3

    def test_the_count_outlives_the_window_it_happened_in(self, clock):
        trace = LoopTrace(window=4, stall_ms=50.0, clock=clock)
        _iterate(trace, clock, [('idle', 0.500)])
        for _ in range(20):
            _iterate(trace, clock, [('draw', 0.001)])
        assert trace.summary()['stalls'] == 1


class TestPhases:
    def test_phase_times_add_up_to_the_iteration(self, clock):
        trace = LoopTrace(clock=clock)
        _iterate(trace, clock, [('poll', 0.001), ('idle', 0.010),
                                ('draw', 0.005)])
        phases = trace.phases_ms()
        assert sum(phases.values()) == pytest.approx(
            trace.summary()['median_ms'])

    def test_a_nested_phase_is_not_charged_to_its_parent_as_well(self, clock):
        trace = LoopTrace(clock=clock)
        with trace.iteration():
            with trace.phase('draw'):
                clock.advance(0.002)                 # draw's own work
                with trace.phase('render'):
                    clock.advance(0.008)
        phases = trace.phases_ms()
        assert phases['draw'] == pytest.approx(2.0)
        assert phases['render'] == pytest.approx(8.0)
        assert sum(phases.values()) == pytest.approx(10.0)

    def test_the_same_phase_twice_in_one_iteration_adds_up(self, clock):
        trace = LoopTrace(clock=clock)
        with trace.iteration():
            for _ in range(2):
                with trace.phase('poll'):
                    clock.advance(0.003)
        assert trace.phases_ms()['poll'] == pytest.approx(6.0)

    def test_phases_are_averaged_over_the_window(self, clock):
        trace = LoopTrace(clock=clock)
        _iterate(trace, clock, [('idle', 0.010)])
        _iterate(trace, clock, [('idle', 0.020)])
        assert trace.phases_ms()['idle'] == pytest.approx(15.0)

    def test_a_phase_an_iteration_never_entered_counts_as_no_time(self, clock):
        trace = LoopTrace(clock=clock)
        _iterate(trace, clock, [('idle', 0.010), ('draw', 0.010)])
        _iterate(trace, clock, [('idle', 0.010)])
        assert trace.phases_ms()['draw'] == pytest.approx(5.0)

    def test_a_phase_outside_an_iteration_is_not_an_error(self, clock):
        """OnDraw is also called from drawPoll and from tests, with no loop."""
        trace = LoopTrace(clock=clock)
        with trace.phase('render'):
            clock.advance(0.005)
        assert trace.summary()['iterations'] == 0

    def test_an_exception_does_not_leave_the_stack_wedged(self, clock):
        trace = LoopTrace(clock=clock)
        with pytest.raises(ValueError):
            with trace.iteration():
                with trace.phase('draw'):
                    raise ValueError('render blew up')
        _iterate(trace, clock, [('idle', 0.010)])
        assert trace.phases_ms()['idle'] == pytest.approx(5.0)


class TestTheStallReport:
    def test_a_stall_keeps_the_breakdown_of_where_its_time_went(self, clock):
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        _iterate(trace, clock, [('poll', 0.001), ('idle', 0.900),
                                ('draw', 0.010)])
        duration, phases = trace.last_stall
        assert duration == pytest.approx(0.911)
        assert phases['idle'] == pytest.approx(0.900)

    def test_the_culprit_is_named(self, clock):
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        _iterate(trace, clock, [('poll', 0.001), ('idle', 0.900),
                                ('draw', 0.010)])
        assert trace.worst_phase() == ('idle', pytest.approx(900.0))

    def test_no_stall_yet_names_nobody(self, clock):
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        _iterate(trace, clock, [('draw', 0.010)])
        assert trace.last_stall is None
        assert trace.worst_phase() is None

    def test_tracing_logs_the_breakdown(self, clock, caplog):
        trace = LoopTrace(stall_ms=50.0, trace=True, clock=clock)
        with caplog.at_level(logging.WARNING, logger='OpenGLContext.looptrace'):
            _iterate(trace, clock, [('poll', 0.001), ('idle', 0.900)])
        assert 'idle' in caplog.text
        assert '901' in caplog.text

    def test_a_quiet_trace_logs_nothing(self, clock, caplog):
        trace = LoopTrace(stall_ms=50.0, trace=False, clock=clock)
        with caplog.at_level(logging.WARNING, logger='OpenGLContext.looptrace'):
            _iterate(trace, clock, [('idle', 0.900)])
        assert caplog.text == ''


class TestWatchingFromAnotherThread:
    """What a sampler needs to know: is this iteration overrunning, right now?

    A stall can only be recognised from outside the main thread, and only while
    it is still happening -- by the time the iteration closes, whatever was on
    the stack has already returned.
    """

    def test_no_iteration_open_means_nothing_to_watch(self, clock):
        assert LoopTrace(clock=clock).iteration_age() is None

    def test_an_open_iteration_reports_how_long_it_has_been_running(self, clock):
        trace = LoopTrace(clock=clock)
        with trace.iteration():
            clock.advance(0.030)
            assert trace.iteration_age() == pytest.approx(0.030)

    def test_it_closes_again_when_the_iteration_ends(self, clock):
        trace = LoopTrace(clock=clock)
        with trace.iteration():
            clock.advance(0.010)
        assert trace.iteration_age() is None

    def test_an_iteration_that_raised_still_closes(self, clock):
        trace = LoopTrace(clock=clock)
        with pytest.raises(ValueError):
            with trace.iteration():
                raise ValueError('boom')
        assert trace.iteration_age() is None

    def test_overrunning_is_false_until_the_threshold_is_crossed(self, clock):
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        assert trace.overrunning() is False        # nothing open
        with trace.iteration():
            clock.advance(0.040)
            assert trace.overrunning() is False
            clock.advance(0.020)
            assert trace.overrunning() is True


class TestListeners:
    def test_a_listener_hears_every_iteration(self, clock):
        heard = []
        trace = LoopTrace(stall_ms=50.0, clock=clock)
        trace.subscribe(lambda d, p, s: heard.append((round(d, 3), s)))
        _iterate(trace, clock, [('draw', 0.010)])
        _iterate(trace, clock, [('idle', 0.500)])
        assert heard == [(0.010, False), (0.500, True)]

    def test_a_listener_is_given_the_phases(self, clock):
        heard = []
        trace = LoopTrace(clock=clock)
        trace.subscribe(lambda d, p, s: heard.append(p))
        _iterate(trace, clock, [('idle', 0.010)])
        assert heard[0]['idle'] == pytest.approx(0.010)

    def test_a_listener_that_raises_does_not_take_the_loop_down(self, clock, caplog):
        """A trace is diagnostic equipment; it does not get to break the frame."""
        trace = LoopTrace(clock=clock)
        trace.subscribe(lambda d, p, s: 1 / 0)
        with caplog.at_level(logging.ERROR, logger='OpenGLContext.looptrace'):
            _iterate(trace, clock, [('draw', 0.010)])
        assert trace.summary()['iterations'] == 1
        assert 'listener' in caplog.text

    def test_several_listeners_all_hear_it(self, clock):
        heard = []
        trace = LoopTrace(clock=clock)
        for index in range(3):
            trace.subscribe(lambda d, p, s, i=index: heard.append(i))
        _iterate(trace, clock, [('draw', 0.010)])
        assert sorted(heard) == [0, 1, 2]


class TestDescribePhases:
    def test_the_worst_comes_first_and_it_reads_in_milliseconds(self):
        assert describe_phases({'poll': 0.001, 'idle': 0.9, 'draw': 0.01}) \
            == 'idle 900ms, draw 10ms, poll 1ms'

    def test_nothing_to_describe_says_so(self):
        assert describe_phases({}) == '-'


class TestConfiguration:
    def test_the_threshold_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_STALL_MS', '12.5')
        assert LoopTrace().stall_seconds == pytest.approx(0.0125)

    def test_a_threshold_that_is_not_a_number_falls_back_to_the_default(
            self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_STALL_MS', 'soon')
        assert LoopTrace().stall_seconds == pytest.approx(
            LoopTrace.DEFAULT_STALL_MS / 1000.0)

    def test_setting_the_threshold_switches_tracing_on(self, monkeypatch):
        """Asking for a threshold is asking to be told when it is crossed."""
        monkeypatch.setenv('OPENGLCONTEXT_STALL_MS', '20')
        assert LoopTrace().trace is True

    def test_tracing_can_be_asked_for_on_its_own(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_TRACE_STALLS', '1')
        assert LoopTrace().trace is True

    def test_by_default_it_counts_but_says_nothing(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_STALL_MS', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_TRACE_STALLS', raising=False)
        trace = LoopTrace()
        assert trace.trace is False
        assert trace.stall_seconds == pytest.approx(
            LoopTrace.DEFAULT_STALL_MS / 1000.0)


class TestTheMostRecentIteration:
    """A caller inside an open iteration cannot be told about that one: the
    phases it is inside have not been charged yet.  It gets the last complete
    one, which is what a session recording writes down."""

    def test_there_is_none_before_the_first_iteration(self, clock):
        assert LoopTrace(clock=clock).last is None

    def test_it_is_the_iteration_that_finished_most_recently(self, clock):
        trace = LoopTrace(clock=clock)
        for seconds in (0.010, 0.020, 0.030):
            with trace.iteration():
                clock.advance(seconds)
        duration, _phases = trace.last
        assert duration == pytest.approx(0.030)

    def test_it_carries_that_iteration_s_own_phases(self, clock):
        trace = LoopTrace(clock=clock)
        with trace.iteration():
            with trace.phase('idle'):
                clock.advance(0.040)
        _duration, phases = trace.last
        assert phases['idle'] == pytest.approx(0.040)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
